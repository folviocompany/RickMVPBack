import hashlib
import time
import uuid
from typing import TypedDict

import pymupdf
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.core.config import Settings
from app.extracta.models import DocumentResult, Line
from app.extracta.ocr import read_page, text_lines
from app.extracta.profiles import recognize, validate_orders
from app.extracta.recovery import CallBudget, recover
from app.services.pdf import InvalidPdfError, validate_pdf


class State(TypedDict):
    content: bytes
    result: DocumentResult
    lines: list[Line]
    use_ocr: list[int]


def build_graph(settings: Settings, budget: CallBudget | None = None):
    def inspect(state: State):
        started = time.perf_counter()
        validate_pdf(state["content"])
        result = state["result"]
        with pymupdf.open(stream=state["content"], filetype="pdf") as doc:
            if doc.needs_pass:
                raise InvalidPdfError("PDF protegido por senha não é suportado")
            if len(doc) > settings.extracta_max_pages_per_document:
                raise InvalidPdfError("PDF excede o limite configurado de páginas")
            result.page_count = len(doc)
            lines, use_ocr = [], []
            for number, page in enumerate(doc, start=1):
                extracted = text_lines(page, number)
                usable = sum(len(line.text) for line in extracted) >= 80
                if usable:
                    lines.extend(extracted)
                else:
                    use_ocr.append(number)
        result.timings["inspection"] = time.perf_counter() - started
        result.transitions.append("inspect")
        return {"lines": lines, "use_ocr": use_ocr, "result": result}

    def ocr(state: State):
        result = state["result"]
        started = time.perf_counter()
        result.ocr_passes += 1
        lines = [line for line in state["lines"] if line.page_number not in state["use_ocr"]]
        psm = 6 if result.ocr_passes == 1 else 4
        with pymupdf.open(stream=state["content"], filetype="pdf") as doc:
            for number in state["use_ocr"]:
                lines.extend(read_page(doc[number - 1], number, settings, psm))
        result.timings["ocr"] = result.timings.get("ocr", 0) + time.perf_counter() - started
        result.transitions.append(f"ocr_psm_{psm}")
        return {"lines": lines, "result": result}

    def extract(state: State):
        result = state["result"]
        started = time.perf_counter()
        profile = recognize(state["lines"])
        result.orders = []
        if profile:
            result.profile_id, result.profile_version = profile.id, profile.version
            result.orders = profile.extract(state["lines"])
        result.timings["extraction"] = (
            result.timings.get("extraction", 0) + time.perf_counter() - started
        )
        result.transitions.append("recognize_extract")
        return {"result": result}

    def validate(state: State):
        result = state["result"]
        started = time.perf_counter()
        validate_orders(result.orders)
        result.timings["validation"] = (
            result.timings.get("validation", 0) + time.perf_counter() - started
        )
        result.transitions.append("validate")
        return {"result": result}

    def route_validation(state: State):
        result = state["result"]
        incomplete = not result.orders or any(
            not order.items
            or order.calculated_product_total is None
            or order.product_total is None
            or abs(order.calculated_product_total - order.product_total) > 0.05
            for order in result.orders
        )
        if incomplete and state["use_ocr"] and result.ocr_passes < 2:
            return "ocr"
        return "recover" if settings.extracta_allow_external_ai else "finish"

    def recover_fields(state: State):
        result = state["result"]
        recover(result, state["lines"], settings, budget)
        result.transitions.append("recover_nvidia")
        return {"result": result}

    def finish(state: State):
        result = state["result"]
        result.status = "needs_review"
        if result.profile_id is None:
            result.warnings.append("Perfil desconhecido; requer classificação humana")
        if not result.orders or not any(order.items for order in result.orders):
            result.warnings.append("Nenhum pedido extraído com segurança")
        result.transitions.append("needs_review")
        return {"result": result}

    graph = StateGraph(State)
    graph.add_node("inspect", inspect)
    graph.add_node("ocr", ocr)
    graph.add_node("extract", extract)
    graph.add_node("validate", validate)
    graph.add_node("finish", finish)
    graph.add_node("recover", recover_fields)
    graph.add_edge(START, "inspect")
    graph.add_conditional_edges("inspect", lambda s: "ocr" if s["use_ocr"] else "extract")
    graph.add_edge("ocr", "extract")
    graph.add_edge("extract", "validate")
    graph.add_conditional_edges("validate", route_validation)
    graph.add_edge("recover", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def analyze_document(
    content: bytes, filename: str, settings: Settings, budget: CallBudget | None = None
) -> DocumentResult:
    started = time.perf_counter()
    result = DocumentResult(
        source_document_id=str(uuid.uuid4()),
        filename=filename,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    try:
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise InvalidPdfError("PDF excede o tamanho máximo configurado")
        with tracing_context(enabled=False):
            state = build_graph(settings, budget).invoke(
                {"content": content, "result": result, "lines": [], "use_ocr": []},
                {"recursion_limit": 16, "callbacks": []},
            )
        result = state["result"]
    except (ValueError, RuntimeError, OSError) as exc:
        result.status = "failed"
        result.errors.append(str(exc))
    result.timings["total"] = time.perf_counter() - started
    return result
