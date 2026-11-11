CONVS = {
    "c-group": {"id": "c-group", "threadType": "group", "externalThreadId": "g99",
                "contact": {"fullName": "Bot Đơn Hàng", "phone": None}},
    "c-nam": {"id": "c-nam", "threadType": "user", "externalThreadId": "u1",
              "contact": {"fullName": "Anh Nam", "phone": "0912345678"}},
}


class FakeCRM:
    def __init__(self):
        self.sent = []
        self.msgs = {}

    def refresh_conversations(self):
        return list(CONVS.values())

    def messages(self, cid, limit=30):
        return list(reversed(self.msgs.get(cid, [])))  # API trả mới nhất trước

    def conversation(self, cid):
        return CONVS.get(cid)

    def find_group(self, key):
        return CONVS["c-group"] if key == "bot don hang" else None

    def send(self, account_id, conv, text):
        self.sent.append((account_id, conv["externalThreadId"], text))


def msg(event, conv, text):
    return {"event": event, "data": {"conversationId": conv, "content": text, "contentType": "text"}}


