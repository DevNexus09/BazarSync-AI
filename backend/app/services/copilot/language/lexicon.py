"""Curated Banglish (romanised Bangla) and Bangla lexicons for the Business Copilot.

The lexicons are deliberately small and business-focused. They serve two jobs:

* language detection: Banglish markers versus English stopwords;
* planning recall: mapping Banglish and Bangla business vocabulary to the
  canonical English terms the deterministic planner, intent classifier and date
  parser already understand.

Nothing here decides which tool runs or which number is reported; the planner
and validators stay authoritative.
"""

from __future__ import annotations

# Function words and verbs that are strong evidence of Banglish. Each one is rare
# or absent in English text.
STRONG_BANGLISH_MARKERS: frozenset[str] = frozenset(
    {
        "ami", "amar", "amake", "amra", "amader", "apni", "apnar", "apnake", "tumi", "tomar",
        "ki", "kii", "keno", "kno", "kn", "kemon", "kmn", "koto", "kotto", "koyta", "koita", "kon", "konta", "konti",
        "koyti", "koiti", "kotogulo", "kotogula", "kothay", "kobe", "kivabe", "kibhabe", "kemne", "keu", "kichu", "kisu",
        "ase", "achhe", "nai", "nei", "hoy", "hoyeche", "hoise", "hoyse", "hoyni", "hoini", "hobe", "hbe",
        "korbo", "korte", "koro", "korun", "kore", "korse", "korche", "korchi", "korsi", "korechi", "korben",
        "dekhao", "dekhan", "dekhaw", "dekhte", "bolo", "bolun", "bujhte", "bujhi", "janao", "janan", "jante",
        "chai", "lagbe", "dorkar", "ekhon", "akhon", "ajke", "aaj", "gotokal", "gotkal", "porshu",
        "theke", "jonno", "jnno", "sathe", "shathe", "moddhe", "beshi", "besi", "kome", "komlo", "kmse",
        "komse", "komeche", "komche", "barlo", "bereche", "barse", "barche", "bareche", "komao", "komabo",
        "komate", "barao", "barabo", "baraw", "baraite", "valo", "bhalo", "kharap", "khub", "onek",
        "shob", "sobcheye", "shobcheye", "ekta", "ekti", "gulo", "guli", "holo", "hocche", "hosse",
        "mash", "maas", "shoptaho", "soptaho", "shoptah", "saptah", "soptah", "bochor", "bosor", "dine",
        "shokal", "bikel", "jodi", "tahole", "kintu", "ebong", "othoba", "uchit", "ucit", "parbo", "pari",
        "bikri", "bikry", "bikroy", "bekri", "bechakena", "daam", "mullo", "mulyo", "labh", "laabh", "lav",
        "lokshan", "lokkhan", "khoroch", "khorcha", "stok", "kreta", "protidwondi", "protijogi", "protijogita",
        "aay", "aai", "rojgar", "jinish", "jinis", "ponno", "pondo", "mojud", "shesh", "sesh", "anbo", "ante",
        "prochar", "chhar", "chhad", "goto", "gotho", "ei", "oi", "eta", "ota", "eita", "oita", "naki",
        "karon", "hoye", "gechilo", "geche", "gese", "dekhe", "dekhun", "nin", "deya", "diye", "tottho", "niche",
        "upore", "shuru", "porjonto", "ager", "thakle", "holeo", "ekhane", "hishebe", "onujayi", "mote", "prai",
        "ektu", "shudhu", "apnader", "jothesto", "proyojon", "proyojone", "bivinno", "cheye", "tobe",
    }
)

# Short or ambiguous tokens that are also English words or very common
# romanisations. They only count for half a marker.
WEAK_BANGLISH_MARKERS: frozenset[str] = frozenset(
    {"ache", "dam", "mal", "din", "rat", "sob", "ta", "ti", "er", "kal", "na", "je", "kom", "aj", "mas", "ar", "pore", "tai"}
)

ENGLISH_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "am", "what", "why", "how", "when", "where",
        "which", "who", "my", "me", "i", "we", "our", "you", "your", "do", "does", "did", "should", "can", "could",
        "would", "will", "of", "for", "in", "on", "to", "and", "or", "with", "from", "about", "show", "give",
        "tell", "much", "many", "last", "this", "that", "these", "those", "there", "it", "its", "have", "has",
        "had", "not", "no", "yes", "please", "any", "all", "some", "more", "most", "less", "than", "if", "then",
        "by", "at", "as", "per", "into", "up", "down", "off", "out", "over", "under", "next", "week", "month", "year",
    }
)

# Banglish token -> canonical English planning terms.
BANGLISH_TERMS: dict[str, tuple[str, ...]] = {
    # sales / revenue
    "bikri": ("sales",), "bikry": ("sales",), "bikroy": ("sales",), "bekri": ("sales",),
    "bechakena": ("sales",), "aay": ("revenue",), "aai": ("revenue",), "rojgar": ("revenue",),
    # price / discount / promotion
    "dam": ("price",), "daam": ("price",), "mullo": ("price",), "mulyo": ("price",),
    "chhar": ("discount",), "chhad": ("discount",), "prochar": ("promotion",),
    # profit / cost
    "lav": ("profit",), "labh": ("profit",), "laabh": ("profit",), "lokshan": ("loss", "profit"), "lokkhan": ("loss", "profit"),
    "khoroch": ("cost",), "khorcha": ("cost",),
    # inventory
    "stok": ("stock",), "mal": ("stock",), "mojud": ("stock",), "shesh": ("out of stock",), "sesh": ("out of stock",),
    "anbo": ("restock",), "ante": ("restock",),
    # catalogue / customers / competitors
    "jinish": ("product",), "jinis": ("product",), "ponno": ("product",), "pondo": ("product",),
    "kreta": ("customer",), "protidwondi": ("competitor",), "protijogi": ("competitor",),
    "protijogita": ("competitor",),
    # direction of change
    "kom": ("low",), "kome": ("drop", "down"), "komlo": ("drop", "down"), "kmse": ("drop", "down"),
    "komse": ("drop", "down"), "komeche": ("drop", "down"), "komche": ("drop", "down"),
    "barlo": ("increase", "up"), "bereche": ("increase", "up"), "bareche": ("increase", "up"),
    "barse": ("increase", "up"), "barche": ("increase", "up"),
    "komao": ("lower",), "komabo": ("lower",), "komate": ("lower",),
    "barao": ("raise",), "barabo": ("raise",), "baraw": ("raise",), "baraite": ("raise",),
    "beshi": ("most",), "besi": ("most",), "sobcheye": ("top",), "shobcheye": ("top",),
    "kharap": ("bad",), "valo": ("good",), "bhalo": ("good",),
    # question words
    "keno": ("why",), "kno": ("why",), "kn": ("why",), "koto": ("how much",), "kotto": ("how much",),
    "koyta": ("how many",), "koita": ("how many",), "koyti": ("how many",), "koiti": ("how many",),
    "kotogulo": ("how many",), "kotogula": ("how many",), "kon": ("which",), "konta": ("which",), "konti": ("which",),
    "kivabe": ("how",), "kibhabe": ("how",), "kemne": ("how",), "kemon": ("how",),
    # time
    "ajke": ("today",), "ajker": ("today",), "aaj": ("today",), "aj": ("today",),
    "gotokal": ("yesterday",), "gotkal": ("yesterday",), "gotobar": ("last time",),
}

# Translation-only Banglish words: they shape the in-order English rendering
# ("amar mot koyta product ache" -> "my total how many products have") but are
# not planning terms on their own.
BANGLISH_FUNCTION_WORDS: dict[str, tuple[str, ...]] = {
    "ami": ("i",), "amar": ("my",), "amader": ("our",), "apni": ("you",), "apnar": ("your",),
    "ache": ("have",), "ase": ("have",), "achhe": ("have",), "nai": ("no",), "nei": ("no",),
    "mot": ("total",), "sob": ("all",), "shob": ("all",), "ki": ("what",), "chilo": ("was",),
    "dao": ("show",), "dekhao": ("show",), "dekhan": ("show",), "dekhaw": ("show",), "bolo": ("tell",), "bolun": ("tell",),
    "korbo": ("should i",), "korbe": ("should i",), "abar": ("again",),
}

# Banglish case/classifier particles ("October e", "product er", "15 ti", "product gulo"); dropped from the rendering.
BANGLISH_PARTICLES: frozenset[str] = frozenset({"e", "er", "ta", "ti", "te", "ke", "gula", "gulo", "guli"})

# Nouns pluralised after "how many" so the rendering matches plural planner phrases.
COUNTABLE_NOUNS: frozenset[str] = frozenset(
    {"product", "order", "customer", "competitor", "alert", "promotion", "unit", "category", "recommendation", "sale", "listing", "item"}
)

# Multi-word Banglish phrases, matched before single tokens.
BANGLISH_PHRASES: dict[str, tuple[str, ...]] = {
    "goto shoptah": ("last week",), "goto shoptaho": ("last week",), "goto soptaho": ("last week",),
    "goto soptah": ("last week",), "goto saptah": ("last week",), "gotho shoptah": ("last week",),
    "ager shoptah": ("last week",), "ei shoptah": ("this week",), "ei shoptaho": ("this week",),
    "ei soptaho": ("this week",), "ei soptah": ("this week",),
    "goto mash": ("last month",), "goto mas": ("last month",), "goto maas": ("last month",),
    "ager mash": ("last month",), "ei mash": ("this month",), "ei mas": ("this month",), "ei maas": ("this month",),
    "goto bochor": ("last year",), "goto bosor": ("last year",), "ei bochor": ("this year",),
    "bikri hoy na": ("no sales", "dead stock"), "bikri hoyni": ("no sales",), "bikri hoini": ("no sales",),
    "stock shesh": ("stockout",), "stok shesh": ("stockout",), "mal shesh": ("stockout",),
    "stock e ache": ("in stock",), "stok e ache": ("in stock",), "stock a ache": ("in stock",), "stock ase": ("in stock",),
    "ki korbo": ("what should i do",), "ki kora uchit": ("what should i do",), "ki korte hobe": ("what should i do",),
    "abar order": ("restock", "reorder"), "dam komabo": ("lower price",), "dam barabo": ("raise price",),
    "ager bar": ("last time",), "business er summary": ("business health",), "business er obostha": ("how is my business",),
}

# Bangla-script business vocabulary -> canonical English planning terms. The
# planner already carries Bangla aliases; these add recall for the classifier,
# the date parser and RAG keywords.
BANGLA_TERMS: dict[str, tuple[str, ...]] = {
    "বিক্রি": ("sales",), "বিক্রয়": ("sales",), "আয়": ("revenue",), "রেভিনিউ": ("revenue",),
    "দাম": ("price",), "মূল্য": ("price",), "ছাড়": ("discount",), "ডিসকাউন্ট": ("discount",),
    "লাভ": ("profit",), "মুনাফা": ("profit",), "খরচ": ("cost",),
    "স্টক": ("stock",), "মজুদ": ("stock",), "পণ্য": ("product",), "প্রোডাক্ট": ("product",),
    "প্রতিযোগী": ("competitor",), "অর্ডার": ("order",), "কেন": ("why",),
    "কয়টি": ("how many",), "কয়টা": ("how many",), "কতগুলো": ("how many",), "কতটি": ("how many",),
    "কমেছে": ("drop", "down"), "কমলো": ("drop", "down"), "বেড়েছে": ("increase", "up"), "বাড়লো": ("increase", "up"),
    "মার্জিন": ("margin",), "লোকসান": ("loss", "profit"), "প্রচারণা": ("promotion",), "প্রমোশন": ("promotion",),
    "সতর্কতা": ("alert",), "পরামর্শ": ("recommendation",), "ডেড": ("dead stock",), "আটকে": ("locked capital",),
    "গতবার": ("last time",),
}

BANGLA_PHRASES: dict[str, tuple[str, ...]] = {
    "গত সপ্তাহ": ("last week",), "এই সপ্তাহ": ("this week",), "গত মাস": ("last month",), "এই মাস": ("this month",),
    "গতকাল": ("yesterday",), "আজ": ("today",), "কী করব": ("what should i do",), "কি করব": ("what should i do",),
    "বিক্রি হয়নি": ("no sales", "dead stock"), "ব্যবসার অবস্থা": ("how is my business",), "ব্যবসার সারাংশ": ("business health",),
}
