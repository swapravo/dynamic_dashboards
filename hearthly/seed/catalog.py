"""Static reference data for the synthetic Hearthly business: geography, products, names."""

from __future__ import annotations

from typing import NamedTuple


class StateInfo(NamedTuple):
    name: str
    region: str
    weight: float
    cities: tuple[str, ...]


STATES: tuple[StateInfo, ...] = (
    StateInfo("Maharashtra", "West", 14, ("Mumbai", "Pune", "Nagpur", "Nashik")),
    StateInfo("Karnataka", "South", 12, ("Bengaluru", "Mysuru", "Mangaluru")),
    StateInfo("Delhi", "North", 10, ("New Delhi",)),
    StateInfo("Tamil Nadu", "South", 8, ("Chennai", "Coimbatore", "Madurai")),
    StateInfo("Telangana", "South", 7, ("Hyderabad", "Warangal")),
    StateInfo("Uttar Pradesh", "North", 6, ("Lucknow", "Noida", "Kanpur", "Varanasi")),
    StateInfo("Gujarat", "West", 6, ("Ahmedabad", "Surat", "Vadodara")),
    StateInfo("West Bengal", "East", 6, ("Kolkata", "Siliguri")),
    StateInfo("Haryana", "North", 4, ("Gurugram", "Faridabad")),
    StateInfo("Kerala", "South", 4, ("Kochi", "Thiruvananthapuram")),
    StateInfo("Rajasthan", "North", 3, ("Jaipur", "Udaipur")),
    StateInfo("Madhya Pradesh", "Central", 3, ("Indore", "Bhopal")),
    StateInfo("Punjab", "North", 2, ("Ludhiana", "Amritsar")),
    StateInfo("Andhra Pradesh", "South", 2, ("Visakhapatnam", "Vijayawada")),
    StateInfo("Odisha", "East", 2, ("Bhubaneswar", "Cuttack")),
    StateInfo("Bihar", "East", 2, ("Patna", "Gaya")),
    StateInfo("Goa", "West", 1, ("Panaji", "Margao")),
    StateInfo("Chhattisgarh", "Central", 1, ("Raipur",)),
    StateInfo("Assam", "Northeast", 3.2, ("Guwahati", "Dibrugarh")),
    StateInfo("Meghalaya", "Northeast", 1.0, ("Shillong",)),
    StateInfo("Tripura", "Northeast", 0.9, ("Agartala",)),
    StateInfo("Manipur", "Northeast", 0.8, ("Imphal",)),
    StateInfo("Arunachal Pradesh", "Northeast", 0.6, ("Itanagar",)),
    StateInfo("Nagaland", "Northeast", 0.5, ("Kohima", "Dimapur")),
    StateInfo("Mizoram", "Northeast", 0.5, ("Aizawl",)),
    StateInfo("Sikkim", "Northeast", 0.5, ("Gangtok",)),
)

NORTHEAST_STATES: tuple[str, ...] = tuple(s.name for s in STATES if s.region == "Northeast")


class ProductInfo(NamedTuple):
    sku: str
    name: str
    category: str
    unit_cost: float
    list_price: float
    weight: float  # relative popularity


PRODUCTS: tuple[ProductInfo, ...] = (
    # Cookware
    ProductInfo("CW-SKL26", "Cast Iron Skillet 26cm", "Cookware", 690, 1499, 3.0),
    ProductInfo("CW-KDI3L", "Tri-Ply Kadai 3L", "Cookware", 1150, 2499, 2.6),
    ProductInfo("CW-TWA28", "Nonstick Tawa 28cm", "Cookware", 420, 899, 3.4),
    ProductInfo("CW-PRC5L", "Stainless Pressure Cooker 5L", "Cookware", 1380, 2899, 2.4),
    ProductInfo("CW-SAU2L", "Hard-Anodised Saucepan 2L", "Cookware", 560, 1199, 2.0),
    ProductInfo("CW-GFP24", "Granite Fry Pan 24cm", "Cookware", 620, 1349, 2.6),
    ProductInfo("CW-TOPE", "Copper-Bottom Tope Set", "Cookware", 980, 1999, 1.2),
    ProductInfo("CW-DUT4L", "Enamel Dutch Oven 4L", "Cookware", 2100, 4499, 1.0),
    # Kitchen appliances
    ProductInfo("KA-KETTLE", "AirBrew Electric Kettle", "Kitchen Appliances", 640, 1399, 5.2),
    ProductInfo("KA-MIX750", "Hearthly Mixer Grinder 750W", "Kitchen Appliances", 1900, 3999, 2.2),
    ProductInfo("KA-HBL400", "Hand Blender 400W", "Kitchen Appliances", 690, 1499, 2.0),
    ProductInfo("KA-IND2K", "Induction Cooktop 2000W", "Kitchen Appliances", 1450, 2999, 1.8),
    ProductInfo("KA-AFR45", "Air Fryer 4.5L", "Kitchen Appliances", 2900, 5999, 2.0),
    ProductInfo("KA-TOAST", "Pop-Up Toaster", "Kitchen Appliances", 820, 1699, 1.4),
    ProductInfo("KA-RICE18", "Electric Rice Cooker 1.8L", "Kitchen Appliances", 1100, 2299, 1.2),
    ProductInfo("KA-SANDW", "Grill Sandwich Maker", "Kitchen Appliances", 760, 1599, 1.4),
    # Tableware
    ProductInfo("TW-DIN12", "Stoneware Dinner Set 12pc", "Tableware", 1650, 3499, 1.6),
    ProductInfo("TW-BRB2", "Brass Serving Bowls (Set of 2)", "Tableware", 880, 1899, 1.4),
    ProductInfo("TW-GLS6", "Glass Tumblers (Set of 6)", "Tableware", 310, 699, 2.6),
    ProductInfo("TW-CPB1L", "Copper Water Bottle 1L", "Tableware", 450, 999, 3.0),
    ProductInfo("TW-MUG2", "Ceramic Mug Pair", "Tableware", 280, 649, 3.2),
    ProductInfo("TW-BTRAY", "Bamboo Serving Tray", "Tableware", 360, 799, 1.6),
    ProductInfo("TW-THALI", "Steel Thali Set 4pc", "Tableware", 520, 1099, 1.8),
    # Storage
    ProductInfo("ST-JAR3", "Airtight Glass Jars (Set of 3)", "Storage", 330, 749, 3.0),
    ProductInfo("ST-MASALA", "Masala Dabba with Spoon", "Storage", 410, 899, 2.4),
    ProductInfo("ST-LUNCH3", "Steel Lunch Box 3-Tier", "Storage", 390, 849, 2.8),
    ProductInfo("ST-FRIDGE4", "Fridge Organiser Bins (Set of 4)", "Storage", 470, 999, 1.6),
    ProductInfo("ST-ATTA10", "Atta Container 10kg", "Storage", 420, 899, 1.4),
    ProductInfo("ST-FLASK", "Vacuum Flask 750ml", "Storage", 380, 849, 2.6),
    # Home decor
    ProductInfo("HD-RUNNER", "Jute Table Runner", "Home Decor", 260, 599, 1.6),
    ProductInfo("HD-DIYA2", "Brass Diya Pair", "Home Decor", 300, 699, 1.4),
    ProductInfo("HD-CUSH2", "Cotton Cushion Covers (Set of 2)", "Home Decor", 290, 649, 2.0),
    ProductInfo("HD-PLANT", "Ceramic Planter Medium", "Home Decor", 340, 749, 1.6),
    ProductInfo("HD-THROW", "Handloom Throw", "Home Decor", 780, 1699, 1.0),
    ProductInfo("HD-CANDLE", "Scented Soy Candle", "Home Decor", 210, 499, 2.4),
    # Cleaning
    ProductInfo("CL-MICRO6", "Microfibre Cloths (Pack of 6)", "Cleaning", 150, 349, 3.4),
    ProductInfo("CL-COIR", "Coconut Coir Scrub Set", "Cleaning", 90, 249, 3.0),
    ProductInfo("CL-SPINMOP", "Spin Mop with Bucket", "Cleaning", 720, 1499, 1.8),
    ProductInfo("CL-DISH1L", "Natural Dishwash Liquid 1L", "Cleaning", 110, 279, 3.6),
    ProductInfo("CL-TOWEL4", "Kitchen Towel Rolls (Pack of 4)", "Cleaning", 120, 299, 3.0),
)

# Festive-season shoppers lean towards gifting and decor categories.
FESTIVE_CATEGORY_BOOST: dict[str, float] = {"Home Decor": 2.2, "Tableware": 1.6}

COURIERS: tuple[tuple[str, float], ...] = (
    ("SwiftShip", 0.30),
    ("Meridian Express", 0.28),
    ("RapidRoute", 0.24),
    ("Kestrel Logistics", 0.18),
)

FIRST_NAMES: tuple[str, ...] = (
    "Aarav", "Aditi", "Aditya", "Ananya", "Anika", "Arjun", "Arnav", "Avni", "Ayaan", "Diya",
    "Gaurav", "Ishaan", "Ishita", "Kabir", "Kavya", "Krishna", "Lakshmi", "Meera", "Mihir",
    "Nandini", "Neha", "Nikhil", "Pooja", "Pranav", "Priya", "Rahul", "Riya", "Rohan", "Saanvi",
    "Sai", "Sameer", "Sanya", "Shreya", "Siddharth", "Sneha", "Tanvi", "Tara", "Varun", "Vihaan",
    "Zara", "Bhavna", "Deepak", "Farah", "Harsh", "Imran", "Jaya", "Karan", "Lalit", "Manisha",
    "Naveen", "Omkar", "Pallavi", "Rekha", "Suresh", "Tenzin", "Usha", "Vikram", "Yash", "Zubin",
    "Lalremruati", "Bidisha", "Chitra", "Dorjee", "Esha", "Gitanjali", "Hemant", "Indira", "Joyeeta",
)

LAST_NAMES: tuple[str, ...] = (
    "Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Shah", "Mehta", "Gupta", "Singh",
    "Kumar", "Das", "Bose", "Banerjee", "Chatterjee", "Mukherjee", "Rao", "Menon", "Pillai",
    "Joshi", "Kulkarni", "Deshpande", "Agarwal", "Kapoor", "Malhotra", "Chopra", "Khan", "Ali",
    "Fernandes", "D'Souza", "Gill", "Sandhu", "Bhattacharya", "Saikia", "Baruah", "Sangma",
    "Lyngdoh", "Singha", "Debbarma", "Lepcha", "Ao", "Hmar", "Naidu", "Hegde", "Shetty",
)

ACQUISITION_CHANNELS: tuple[tuple[str, float], ...] = (
    ("organic_search", 0.27),
    ("paid_social", 0.22),
    ("search_ads", 0.17),
    ("referral", 0.12),
    ("influencer", 0.10),
    ("email", 0.05),
    ("marketplace", 0.07),
)

ORDER_CHANNELS: tuple[tuple[str, float], ...] = (("web", 0.48), ("app", 0.42), ("marketplace", 0.10))

PAYMENT_METHODS: tuple[tuple[str, float], ...] = (
    ("upi", 0.52),
    ("card", 0.22),
    ("cod", 0.17),
    ("netbanking", 0.06),
    ("wallet", 0.03),
)

TICKET_CHANNELS: tuple[tuple[str, float], ...] = (
    ("chat", 0.38),
    ("email", 0.30),
    ("whatsapp", 0.22),
    ("phone", 0.10),
)

# Median minutes to first response, by ticket channel.
FIRST_RESPONSE_MEDIAN: dict[str, float] = {"chat": 4, "whatsapp": 18, "phone": 2, "email": 210}

REFUND_REASONS: tuple[tuple[str, float], ...] = (
    ("changed_mind", 0.27),
    ("defective", 0.22),
    ("damaged_in_transit", 0.19),
    ("not_as_described", 0.20),
    ("wrong_item", 0.12),
)
