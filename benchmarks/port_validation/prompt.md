Fix validate_port(value) in ports.py.

It must return value unchanged only when value is a Python int from 1 through
65535, inclusive. Reject booleans, all other types, and out-of-range integers by
raising ValueError. Do not coerce strings or floats. Edit only ports.py.

Use the file tools to inspect and fix the code. Report the change when finished.
