class UnionFind:
    def __init__(self):
        self.parent = {}
        self.rank = {}

    def make_set(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x):
        p = self.parent[x]
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent[x]

    def union(self, x, y):
        rx = self.find(x)
        ry = self.find(y)
        if rx == ry:
            return rx
        if self.rank[rx] < self.rank[ry]:
            self.parent[rx] = ry
            return ry
        if self.rank[rx] > self.rank[ry]:
            self.parent[ry] = rx
            return rx
        self.parent[ry] = rx
        self.rank[rx] += 1
        return rx
