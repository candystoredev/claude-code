"""Tests for extract_sizes.py"""

from extract_sizes import extract_size

CASES = [
    ("CANDY NECKLACE UNWRAPPED 0.74 OZ", "0.74 OZ"),
    ("CANDY NECKLACE WRAPPED 0.74 OZ", "0.74 OZ"),
    ("CINNAMON CUBE POPS TUB 0.74 OZ", "0.74 OZ"),
    ("ICE CUBES ICE CHOCOLATE BOX", ""),
    ("TONY'S CHOCOLONELY DARK CHOCOLATE TINYS 0.317 OZ", "0.317 OZ"),
    ("TONY'S CHOCOLONELY MILK CHOCOLATE TINYS 0.317 OZ", "0.317 OZ"),
    ("TONY'S CHOCOLONELY MILK CHOCOLATE CARAMEL SEA SALT TINYS 0.317 OZ", "0.317 OZ"),
    ("MADELAINE MINI MILK CHOCOLATE FOILED CARS 0.5 OZ", "0.5 OZ"),
    ("EFRUTTI GUMMI TACO 0.32 OZ", "0.32 OZ"),
    ("EFRUTTI SOUR MINI BURGERS 0.32 OZ", "0.32 OZ"),
    ("EFRUTTI GUMMI MINI BULK HOT DOGS 0.32 OZ", "0.32 OZ"),
    ("GUMMY BURGERS MINI 0.32 OZ", "0.32 OZ"),
    ("REESE'S PEANUT BUTTER CUPS 0.31 OZ", "0.31 OZ"),
    ("OREO 1.59 OZ 4 PIECE", "1.59 OZ"),
    ("GOLDKENN - BAR - MALIBU RUM - 3.5OZ", "3.5OZ"),   # no space before OZ
    ("LINDT SWISS MILK CHOCOLATE HAZELNUT 10.6 OZ BAR", "10.6 OZ"),
    ("PRETZ PIZZA BAKED SNACK STICKS 1.09 OZ BOX", "1.09 OZ"),
    ("PRETZ SOUR CREAM & ONION BAKED SNACK STICKS 1.09 OZ BOX", "1.09 OZ"),
    ("", ""),
]


def test_all():
    failures = []
    for name, expected in CASES:
        result = extract_size(name)
        if result != expected:
            failures.append(f"  FAIL: {name!r}\n    expected {expected!r}, got {result!r}")

    if failures:
        print("FAILURES:")
        print("\n".join(failures))
        raise SystemExit(1)
    else:
        print(f"All {len(CASES)} tests passed.")


if __name__ == "__main__":
    test_all()
