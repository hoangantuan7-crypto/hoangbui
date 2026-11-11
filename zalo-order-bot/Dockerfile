FROM python:3.13-slim
WORKDIR /app
# anthropic chỉ dùng khi đặt ANTHROPIC_API_KEY (đọc đơn viết tự do)
RUN pip install --no-cache-dir anthropic
COPY bot ./bot
ENV DB_PATH=/data/orders.db TZ=Asia/Ho_Chi_Minh
VOLUME /data
CMD ["python", "-m", "bot.crm_main"]
