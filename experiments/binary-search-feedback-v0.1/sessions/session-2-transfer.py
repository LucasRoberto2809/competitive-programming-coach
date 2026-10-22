import sys


def max_min_distance(positions, k):
    positions.sort()

    def can_place(distance):
        cows_placed = 1
        last_position = positions[0]

        for position in positions[1:]:
            if position - last_position >= distance:
                cows_placed += 1
                last_position = position
                if cows_placed >= k:
                    return True

        return False

    low = 0  # works: positions are distinct, and k <= n
    high = positions[-1] - positions[0] + 1  # sentinel that cannot work

    while high > low + 1:
        mid = (low + high) // 2
        if can_place(mid):
            low = mid
        else:
            high = mid

    return low


n, k = map(int, sys.stdin.readline().split())
positions = list(map(int, sys.stdin.readline().split()))
print(max_min_distance(positions, k))
