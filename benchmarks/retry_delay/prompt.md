Fix retry_delay(attempt) in retry.py.

For a nonnegative Python int, return min(2 ** attempt, 30) as an int, in
seconds. Attempt 0 returns 1. Support arbitrarily large Python integers
without constructing a huge power. Reject bool, other types, and negative
integers by raising ValueError. Edit only retry.py. Use file tools to inspect
and fix it.
