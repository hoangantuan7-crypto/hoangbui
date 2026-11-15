FROM python:3.13-slim
WORKDIR /app
# anthropic chỉ dùng khi đặt ANTHROPIC_API_KEY (đọc đơn viết tự do)
RUN pip install --no-cache-dir anthropic || echo "Không cài được anthropic: bot vẫn chạy, chỉ tắt phần AI"
# Pillow: làm nét ảnh trước khi đọc chữ miễn phí (OCR)
RUN pip install --no-cache-dir pillow || echo "Không cài được Pillow: OCR đọc ảnh gốc"
# Tesseract: đọc chữ trong ảnh thông tin khách miễn phí (tiếng Việt). Không cài được thì bot vẫn chạy.
RUN (apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie \
     && rm -rf /var/lib/apt/lists/*) || echo "Không cài được tesseract: ảnh thông tin khách cần AI để đọc"
COPY bot ./bot
ENV DB_PATH=/data/orders.db TZ=ICT-7
# Giờ Việt Nam (UTC+7) – dạng POSIX nên không cần gói tzdata
VOLUME /data
CMD ["python", "-m", "bot.crm_main"]
