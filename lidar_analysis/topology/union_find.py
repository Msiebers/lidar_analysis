from __future__ import annotations


class UnionFind:
    def __init__(self):
        self.parent = {}
        self.rank = {}

    def add(self, x, weight=None):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x):
        p = self.parent.get(x, x)
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent.get(x, x)

    def union(self, a, b):
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def __contains__(self, x):
        return x in self.parent

    def __getitem__(self, x):
        return self.find(x)
