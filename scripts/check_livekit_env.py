from dotenv import dotenv_values

v = dotenv_values(".env.local")
for key in ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]:
    value = v.get(key) or ""
    print(key)
    print("  present", bool(value))
    print("  length", len(value))
    print("  has_whitespace", value != value.strip())
    print("  wrapped_in_quotes", len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'")
    if key == "LIVEKIT_URL":
        print("  scheme", value.split(":", 1)[0] if ":" in value else "missing")
        print("  looks_livekit_cloud", ("livekit.cloud" in value) or ("livekit.io" in value))
    if key == "LIVEKIT_API_KEY":
        print("  starts_with_API", value.startswith("API"))
