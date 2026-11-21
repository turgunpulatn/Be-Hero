# test_ocr.py
# Usage: python test_ocr.py [image_path]     (default: sample.png)
import sys
import os
import ollama

MODEL = "hf.co/JahongirB/uzocr-8b-GGUF"
PROMPT = "Rasmdagi barcha matnni aniq nusxalab ber. Hech narsa qo'shma, faqat matnni o'zini ber."


def main():
    image_path = sys.argv[1] if len(sys.argv) > 1 else "sample.png"

    if not os.path.isfile(image_path):
        print(f"❌ Файл не найден: {image_path}")
        sys.exit(1)

    print(f"📷 Отправляю {image_path} в модель {MODEL}...")

    try:
        # The ollama library accepts a file path directly, so no manual base64 is needed.
        response = ollama.chat(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": PROMPT,
                "images": [image_path],
            }],
            options={"temperature": 0},  # deterministic OCR, same as analyze.py
        )
    except ollama.ResponseError as e:
        print(f"❌ Ошибка Ollama: {e.error}")
        print(f"   Модель скачана? Проверь: ollama pull {MODEL}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        print("   Ollama запущен? Проверь: ollama serve")
        sys.exit(1)

    text = response["message"]["content"]
    print("\n✅ Распознанный текст:\n")
    print("-" * 50)
    print(text)
    print("-" * 50)
    print(f"Длина: {len(text)} символов")
    if len(text.strip()) < 20:
        print("⚠️ Очень короткий результат — проверь качество изображения.")


if __name__ == "__main__":
    main()