import sys


def min_speed(piles, h):
    def can_finish(speed):
        hours = 0
        for pile in piles:
            hours += (pile + speed - 1) // speed
            if hours > h:
                return False
        return True

    low = 0  # impossible speed
    high = max(piles)  # works: at most one hour per pile

    while high > low + 1:
        mid = (low + high) // 2
        if can_finish(mid):
            high = mid
        else:
            low = mid

    return high


n, h = map(int, sys.stdin.readline().split())
piles = list(map(int, sys.stdin.readline().split()))
print(min_speed(piles, h))
