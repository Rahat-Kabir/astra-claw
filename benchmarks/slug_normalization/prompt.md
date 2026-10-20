Fix slugify(text) in slug.py. Input is always a Python str.

Convert the input to lowercase with str.lower(). Keep only ASCII letters a-z
and digits 0-9. Replace each consecutive group of other characters with one
hyphen. Remove leading and trailing hyphens. Return a str. Empty input, or
input with no kept characters, must return an empty string. Do not transliterate
Unicode characters. Edit only slug.py. Use file tools to inspect and fix it.
