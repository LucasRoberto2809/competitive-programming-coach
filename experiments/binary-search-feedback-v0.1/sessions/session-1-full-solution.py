import sys


def min_capacity(weights, D):
    def can_ship(capacity):
        days_used = 1
        load_today = 0

        for weight in weights:
            if load_today + weight > capacity:
                days_used += 1
                load_today = weight
            else:
                load_today += weight

        return days_used <= D

    low = max(weights) - 1  # fails
    high = sum(weights)     # works

    while high > low + 1:
        mid = (low + high) // 2
        if can_ship(mid):
            high = mid
        else:
            low = mid

    return high


n, D = map(int, sys.stdin.readline().split())
weights = list(map(int, sys.stdin.readline().split()))
print(min_capacity(weights, D))
