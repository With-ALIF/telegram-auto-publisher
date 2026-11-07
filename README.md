# Telegram Auto Publisher

একটি সম্পূর্ণ স্বয়ংক্রিয় এবং সার্ভারলেস টেলিগ্রাম চ্যানেল অটো পাবলিশার। এটি **Python** এবং **GitHub Actions** ব্যবহার করে নির্দিষ্ট সময়সূচী (Schedule) অনুযায়ী টেলিগ্রাম চ্যানেলে টেক্সট, ছবি ও ভিডিও পোস্ট করে। কোনো সার্ভার বা পেইড হোস্টিং ছাড়াই এটি পরিচালিত হয়।

---

## 📁 Project Directory

```yaml

├── .github/
│   └── workflows/
│       └── publisher.yml      # GitHub Actions শিডিউল ও অটোমেশন
├── data/
│   ├── messages.json          # শিডিউল করা মেসেজ তালিকা
│   └── state.json             # ডুপ্লিকেট পোস্টিং রোধের স্টেট ট্র্যাকিং
├── src/
│   ├── __init__.py            # প্যাকেজ এক্সপোর্ট
│   ├── config.py              # এনভায়রনমেন্ট কনফিগারেশন
│   ├── logger.py              # সিক্রেট মাস্কিং সুবিধাসহ লগার
│   ├── message_manager.py     # মেসেজ ভ্যালিডেশন ও ফিল্টারিং
│   └── publisher.py           # Telegram API সংযোগ ও পাবলিশার
├── main.py                    # প্রধান এক্সিকিউশন ফাইল
├── requirements.txt           # প্রয়োজনীয় ডিপেন্ডেন্সিস
├── .gitignore                 # সেনসিটিভ ফাইল সুরক্ষা
└── README.md                  # প্রজেক্ট পরিচিতি ও গাইড
```

---

## ⚙️ Configuration

### ১. GitHub Secrets সেটআপ
GitHub রিপোজিটরির **Settings** > **Secrets and variables** > **Actions**-এ গিয়ে নিচের দুটি সিক্রেট যোগ করুন:

| Secret Name | বিবরণ | উদাহরণ |
| :--- | :--- | :--- |
| `BOT_TOKEN` | @BotFather থেকে পাওয়া এপিআই টোকেন | `9009205433:AAHZ...` |
| `CHANNEL_ID` | টেলিগ্রাম চ্যানেল আইডি বা ইউজারনেম | `@your_channel` বা `-1001234567890` |

---

## 📝 Message Configuration (`data/messages.json`)

মেসেজ যোগ বা পরিবর্তন করতে `data/messages.json` ফাইলে এন্ট্রি দিন:

```json
{
  "messages": [
    {
      "id": "msg_001",
      "time": "08:00",
      "type": "photo",
      "text": "🌅 <b>শুভ সকাল!</b>",
      "image_url": "https://picsum.photos/1200/800",
      "enabled": true
    },
    {
      "id": "msg_002",
      "time": "14:00",
      "type": "text",
      "text": "💡 <b>দুপুরের আপডেট!</b>",
      "enabled": true
    }
  ]
}
```

- `time`: বাংলাদেশ সময় (২৪ ঘণ্টার ফরম্যাট `HH:MM`)।
- `type`: `text`, `photo` অথবা `video`।
- `enabled`: `true` দিলে পোস্ট হবে, `false` দিলে স্কিপ করবে।

---

## ⏰ Schedule Configuration (`.github/workflows/publisher.yml`)

GitHub Actions ক্রন **UTC** সময় ব্যবহার করে (বাংলাদেশ সময় - ৬ ঘণ্টা):

```yaml
on:
  schedule:
    - cron: '0 2 * * *'   # সকাল ০৮:০০ BST
    - cron: '0 8 * * *'   # দুপুর ১৪:০০ BST
    - cron: '0 16 * * *'  # রাত ২২:০০ BST
```

---