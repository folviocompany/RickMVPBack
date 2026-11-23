import asyncio
import re
from decimal import Decimal

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.core.config import Settings
from app.schemas.extraction import DocumentoExtraido

SYSTEM_PROMPT = """Você extrai pedidos de compra que contêm produtos da BIC
a partir de texto de PDF ou OCR.
Retorne somente JSON válido, seguindo exatamente o schema fornecido.

Regras importantes:
- O cliente é a empresa compradora e a BIC é a fornecedora.
- O CNPJ do cliente é o CNPJ da empresa compradora. Use null se não estiver legível.
- Não concatene seq_bic, ref_cliente e codigo_produto.
- Use codigo_produto para o SKU/código principal quando o documento não identificar explicitamente
  o campo como sequência BIC ou referência do cliente.
- Extraia todos os produtos e preserve zeros à esquerda nos códigos.
- Um documento pode conter mais de um pedido e um pedido pode ocupar várias páginas.
- Considere cabeçalhos repetidos em páginas seguintes como continuação, não como novo pedido.
- Quantidade vem da coluna Qtde/Quantidade e valor_unitario da coluna Unitário/Valor Unitário.
- Cada item pode trazer OCR detalhado e OCR suplementar do mesmo trecho. Compare ambos:
  use a visão geral para localizar colunas e a detalhada para distinguir caracteres.
- A quantidade é o pequeno inteiro logo após a data de entrega; nunca use o Peso, que aparece
  perto do fim do bloco e normalmente contém vírgula decimal.
- valor_unitario é o número impresso na coluna Unitário. Preserve-o exatamente; não divida pela
  quantidade e não recalcule o valor.
- Retorne valores monetários como número JSON com ponto decimal (exemplo: 128.22).
- embalagem_cx deve ser apenas um inteiro simples; use null para padrões compostos como
  0040X0012X1UND.
- Cada descrição de mercadoria representa um item. Percorra todas as páginas e não omita itens,
  inclusive quando a descrição, o código, a quantidade e o preço estiverem em linhas separadas.
- Nestes pedidos, o código principal normalmente é o primeiro código com zeros à esquerda antes
  de uma barra na linha de embalagem (exemplo: 00013881/156). Preserve esse código em
  codigo_produto e não o substitua pelo EAN de 13 ou 14 dígitos.
- Antes de responder, conte as descrições de mercadoria no texto e confira se todas viraram itens.
- Use null quando um campo não existir; nunca invente valores.
"""

OUTPUT_FORMAT = """{
  "pedidos": [{
    "numero_pedido": "string ou null",
    "cnpj_cliente": "string ou null",
    "codigo_fornecedor": "string ou null",
    "prazo_pagamento": "string ou null",
    "data_emissao": "string ou null",
    "previsao_entrega": "string ou null",
    "data_limite_entrega": "string ou null",
    "condicao_frete": "string ou null",
    "itens": [{
      "seq_bic": "string ou null",
      "ref_cliente": "string ou null",
      "codigo_produto": "string ou null",
      "ean": "string ou null",
      "descricao": "string ou null",
      "quantidade": 1,
      "embalagem_cx": null,
      "valor_unitario": 0.0,
      "valor_total": null,
      "observacao": null
    }]
  }]
}"""

SUPPLEMENTAL_MARKER = "--- OCR SUPLEMENTAR DE PÁGINAS COMPLETAS ---"


def _primary_ocr_text(document_text: str) -> str:
    return document_text.split(SUPPLEMENTAL_MARKER, maxsplit=1)[0].strip()


def bic_item_candidates(document_text: str) -> list[str]:
    document_text = _primary_ocr_text(document_text)
    ignored_terms = ("FORNECEDOR", "PEDIDO", "COMPRA", "CNPJ", "TOTAIS")
    return [
        line.strip()
        for line in document_text.splitlines()
        if re.search(r"\bBIC\b", line, flags=re.IGNORECASE)
        and not any(term in line.upper() for term in ignored_terms)
    ]


def count_bic_item_candidates(document_text: str) -> int:
    return len(bic_item_candidates(document_text))


def build_bic_item_blocks(document_text: str) -> tuple[str, list[str]]:
    primary_text, separator, supplemental_text = document_text.partition(SUPPLEMENTAL_MARKER)
    lines = primary_text.splitlines()
    ignored_terms = ("FORNECEDOR", "PEDIDO", "COMPRA", "CNPJ", "TOTAIS")
    indexes = [
        index
        for index, line in enumerate(lines)
        if re.search(r"\bBIC\b", line, flags=re.IGNORECASE)
        and not any(term in line.upper() for term in ignored_terms)
    ]
    if not indexes:
        return document_text, []

    blocks = []
    for position, start in enumerate(indexes):
        end = indexes[position + 1] if position + 1 < len(indexes) else len(lines)
        block_lines = []
        for line in lines[start:end]:
            if block_lines and (line.startswith("--- PÁGINA") or "TOTAIS" in line.upper()):
                break
            block_lines.append(line)
        blocks.append("\n".join(block_lines).strip())

    header = "\n".join(lines[: indexes[0]]).strip()
    if separator and supplemental_text.strip():
        supplemental_header, supplemental_blocks = build_bic_item_blocks(
            supplemental_text.strip()
        )
        header = (
            f"{header}\n\n--- OCR SUPLEMENTAR DO CABEÇALHO ---\n{supplemental_header}"
        )
        blocks = [
            (
                f"{block}\n\n--- OCR SUPLEMENTAR DO MESMO ITEM ---\n"
                f"{supplemental_blocks[index]}"
                if index < len(supplemental_blocks)
                else block
            )
            for index, block in enumerate(blocks)
        ]
    return header, blocks


def _normalized_description(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", (value or "").upper()).strip()


def _extract_quantity(block: str) -> int | None:
    lines = block.splitlines()
    date_index = next(
        (index for index, line in enumerate(lines) if re.search(r"\b\d{2}/\d{2}\b", line)),
        None,
    )
    if date_index is None:
        return None
    for line in lines[date_index + 1 : date_index + 7]:
        match = re.fullmatch(r"\s*(\d{1,6})\s*", line)
        if match and int(match.group(1)) > 0:
            return int(match.group(1))
    return None


def _extract_unit_price(block: str) -> Decimal | None:
    lines = block.splitlines()
    date_index = next(
        (index for index, line in enumerate(lines) if re.search(r"\b\d{2}/\d{2}\b", line)),
        None,
    )
    if date_index is None:
        return None
    for line in lines[date_index + 1 : date_index + 8]:
        match = re.search(r"(\d{1,6}(?:\.\d{3})*,\s*\d{2})", line)
        if match:
            normalized = match.group(1).replace(".", "").replace(" ", "").replace(",", ".")
            value = Decimal(normalized)
            if value > 0:
                return value
        missing_comma = re.fullmatch(r"\s*(\d{3,5})0(\d{2})(?:\s+.*)?", line)
        if missing_comma:
            value = Decimal(f"{missing_comma.group(1)}.{missing_comma.group(2)}")
            if value > 0:
                return value
    return None


def _code_candidates(block: str, detail_priority: int) -> list[tuple[tuple[int, int, int], str]]:
    candidates = []
    for match in re.finditer(r"\b([A-Z0-9 ]{6,12})/(\d{3})\b", block.upper()):
        raw = re.sub(r"\s+", "", match.group(1))
        if re.search(r"[A-BE-WYZ]", raw):
            continue
        normalized = raw.translate(str.maketrans({"C": "0", "O": "0", "X": "0"}))
        if not normalized.isdigit():
            continue
        normalized = normalized[-8:].zfill(8)
        leading_zeros = len(normalized) - len(normalized.lstrip("0"))
        score = (
            -abs(leading_zeros - 3),
            detail_priority,
            -match.start(),
        )
        candidates.append((score, normalized))
    return candidates


def _apply_block_facts(extraction: DocumentoExtraido, blocks: list[str]) -> None:
    items = [item for order in extraction.pedidos for item in order.itens]
    if len(items) != len(blocks):
        return
    for item, combined_block in zip(items, blocks, strict=True):
        detail, separator, supplemental = combined_block.partition(
            "--- OCR SUPLEMENTAR DO MESMO ITEM ---"
        )
        quantity = _extract_quantity(supplemental) if separator else None
        quantity = quantity or _extract_quantity(detail)
        if quantity is not None:
            item.quantidade = quantity

        unit_price = _extract_unit_price(detail)
        unit_price = unit_price or (_extract_unit_price(supplemental) if separator else None)
        if unit_price is not None:
            item.valor_unitario = unit_price

        codes = _code_candidates(detail, detail_priority=1)
        if separator:
            codes.extend(_code_candidates(supplemental, detail_priority=0))
        if codes:
            _, code = max(codes)
            item.seq_bic = None
            item.ref_cliente = None
            item.codigo_produto = code

        description_lines = [
            line.strip()
            for line in combined_block.splitlines()
            if re.search(r"\bBIC\b", line, flags=re.IGNORECASE)
        ]
        if description_lines:
            longest_description = max(description_lines, key=len)
            if len(longest_description) > len(item.descricao or "") * 1.25:
                item.descricao = longest_description


def _extract_payment_terms(header: str) -> str | None:
    lines = header.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if "CONDICOES" in line.upper() and "PAGTO" in line.upper()
        ),
        None,
    )
    if start is None:
        return None
    for line in lines[start + 1 : start + 7]:
        match = re.fullmatch(r"\s*(\d{1,4})\s*", line)
        if match:
            return match.group(1)
    return None


class NvidiaExtractionProvider:
    def __init__(self, settings: Settings):
        if settings.nvidia_api_key is None:
            raise RuntimeError("NVIDIA_API_KEY não configurada")
        self.model = settings.nvidia_model
        self.client = AsyncOpenAI(
            api_key=settings.nvidia_api_key.get_secret_value(),
            base_url=settings.nvidia_base_url,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception_type(
            (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
        ),
        reraise=True,
    )
    async def extract_orders(self, document_text: str) -> DocumentoExtraido:
        candidates = bic_item_candidates(document_text)
        header, blocks = build_bic_item_blocks(document_text)
        if not blocks:
            return await self._extract_chunk(document_text, [], [], 0)

        batch_size = 4
        tasks = []
        for offset in range(0, len(blocks), batch_size):
            tasks.append(
                self._extract_chunk(
                    header,
                    candidates[offset : offset + batch_size],
                    blocks[offset : offset + batch_size],
                    offset,
                )
            )
        partial_extractions = await asyncio.gather(*tasks)

        merged_orders = {}
        header_fields = (
            "cnpj_cliente",
            "codigo_fornecedor",
            "prazo_pagamento",
            "data_emissao",
            "previsao_entrega",
            "data_limite_entrega",
            "condicao_frete",
        )
        for extraction in partial_extractions:
            for order in extraction.pedidos:
                key = order.numero_pedido or "__pedido_sem_numero__"
                existing = merged_orders.get(key)
                if existing is None:
                    merged_orders[key] = order.model_copy(deep=True)
                    continue
                existing.itens.extend(order.itens)
                for field in header_fields:
                    if getattr(existing, field) is None and getattr(order, field) is not None:
                        setattr(existing, field, getattr(order, field))

        result = DocumentoExtraido(pedidos=list(merged_orders.values()))
        payment_terms = _extract_payment_terms(header)
        if payment_terms:
            for order in result.pedidos:
                if order.prazo_pagamento is None:
                    order.prazo_pagamento = payment_terms
        total_items = sum(len(order.itens) for order in result.pedidos)
        if total_items != len(candidates):
            raise RuntimeError(
                f"A extração consolidada retornou {total_items} itens, mas o OCR identificou "
                f"{len(candidates)} descrições de produtos"
            )
        descriptions = [
            _normalized_description(item.descricao)
            for order in result.pedidos
            for item in order.itens
        ]
        if len(set(descriptions)) != len(candidates):
            raise RuntimeError("A extração consolidada contém descrições de produtos repetidas")
        return result

    async def _extract_chunk(
        self,
        header: str,
        candidates: list[str],
        blocks: list[str],
        offset: int,
    ) -> DocumentoExtraido:
        expected_items = len(candidates)
        count_control = ""
        if candidates:
            candidate_list = "\n".join(
                f"{offset + number}. {description}"
                for number, description in enumerate(candidates, start=1)
            )
            count_control = (
                "\nCONTAGEM DE CONTROLE: o OCR contém "
                f"{expected_items} descrições candidatas de produtos com a palavra BIC. "
                f"A soma dos itens no JSON deve ser exatamente {expected_items}. "
                "Crie um item para cada linha numerada abaixo, sem repetir nenhuma:\n"
                f"{candidate_list}"
            )
        formatted_blocks = "\n\n".join(
            f"--- ITEM CANDIDATO {offset + number} ---\n{block}"
            for number, block in enumerate(blocks, start=1)
        )
        structured_text = (
            f"{header}\n\n{formatted_blocks}".strip() if blocks else header
        )
        prompt = (
            f"{SYSTEM_PROMPT}{count_control}\nFORMATO EXATO DA RESPOSTA:\n{OUTPUT_FORMAT}"
            "\nPreencha esse formato com os dados; não retorne uma descrição do formato."
            "\nCada seção ITEM CANDIDATO deve gerar exatamente um item correspondente no JSON."
            f"\n\nTEXTO DO PDF SEGMENTADO:\n{structured_text}"
        )
        last_error = "A NVIDIA não retornou uma extração válida"
        for attempt in range(2):
            attempt_prompt = prompt
            if attempt and expected_items:
                attempt_prompt += (
                    "\n\nCORREÇÃO OBRIGATÓRIA: a resposta anterior omitiu ou duplicou itens. "
                    f"Revise cada linha e retorne exatamente {expected_items} itens."
                )
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": attempt_prompt}],
                temperature=0.1,
                max_tokens=4096,
                response_format={"type": "json_object"},
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            content = response.choices[0].message.content
            if not content:
                last_error = "A NVIDIA retornou uma resposta vazia"
                continue
            try:
                extraction = DocumentoExtraido.model_validate_json(content)
            except ValidationError as exc:
                details = "; ".join(
                    f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                    for error in exc.errors(include_input=False, include_url=False)[:5]
                )
                last_error = f"Resposta da IA não corresponde ao schema esperado: {details}"
                continue

            _apply_block_facts(extraction, blocks)

            actual_items = sum(len(order.itens) for order in extraction.pedidos)
            if expected_items and actual_items != expected_items:
                last_error = (
                    f"A IA retornou {actual_items} itens, mas o OCR identificou "
                    f"{expected_items} descrições de produtos"
                )
                continue
            descriptions = [
                _normalized_description(item.descricao)
                for order in extraction.pedidos
                for item in order.itens
            ]
            if expected_items and len(set(descriptions)) != expected_items:
                last_error = (
                    "A IA repetiu descrições de produtos em vez de cobrir todas as linhas do OCR"
                )
                continue
            return extraction

        raise RuntimeError(last_error)
