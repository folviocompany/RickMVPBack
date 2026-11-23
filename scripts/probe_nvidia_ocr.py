import argparse
import base64

import httpx
import pymupdf

from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    args = parser.parse_args()

    with pymupdf.open(args.pdf) as document:
        page = document[0]
        image = page.get_pixmap(dpi=120, colorspace=pymupdf.csGRAY, alpha=False).tobytes(
            "jpeg", jpg_quality=65
        )

    settings = get_settings()
    response = httpx.post(
        "https://ai.api.nvidia.com/v1/cv/nvidia/nemotron-ocr-v2",
        headers={
            "Authorization": f"Bearer {settings.nvidia_api_key.get_secret_value()}",
            "Accept": "application/json",
        },
        json={
            "input": [
                {
                    "type": "image_url",
                    "url": f"data:image/jpeg;base64,{base64.b64encode(image).decode()}",
                }
            ],
            "merge_levels": ["paragraph"],
        },
        timeout=90,
    )
    print("HTTP:", response.status_code)
    response.raise_for_status()
    payload = response.json()
    print("Campos:", sorted(payload))
    for key, value in payload.items():
        size = len(value) if isinstance(value, (dict, list, str)) else None
        print(f"- {key}: {type(value).__name__}, tamanho={size}")
    first = payload.get("data", [{}])[0]
    print("Campos de data[0]:", sorted(first))
    for key, value in first.items():
        size = len(value) if isinstance(value, (dict, list, str)) else None
        print(f"  - {key}: {type(value).__name__}, tamanho={size}")
    detection = first.get("text_detections", [{}])[0]
    print("Campos de text_detections[0]:", sorted(detection))
    for key, value in detection.items():
        size = len(value) if isinstance(value, (dict, list, str)) else None
        print(f"    - {key}: {type(value).__name__}, tamanho={size}")
    prediction = detection.get("text_prediction", {})
    print("Campos de text_prediction:", sorted(prediction))


if __name__ == "__main__":
    main()
