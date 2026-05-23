class UnionFind:
    """
    Union-find data structure compatible with the legacy imagepers.py code.

    Legacy API:
      uf.add(item, weight)
      item in uf
      uf[item]
      uf.union(item1, item2, ...)

    Compatibility aliases:
      uf.make_set(item)
      uf.find(item)
      uf.parent
    """

    def __init__(self):
        self.weights = {}
        self.parents = {}

    @property
    def parent(self):
        # Compatibility for newer code that expects uf.parent
        return self.parents

    def add(self, obj, weight=1):
        if obj not in self.parents:
            self.parents[obj] = obj
            self.weights[obj] = weight

    def make_set(self, obj):
        # Compatibility alias
        self.add(obj, 1)

    def __contains__(self, obj):
        return obj in self.parents

    def __getitem__(self, obj):
        if obj not in self.parents:
            raise KeyError(obj)

        path = [obj]
        root = self.parents[obj]

        while root != path[-1]:
            path.append(root)
            root = self.parents[root]

        for ancestor in path:
            self.parents[ancestor] = root

        return root

    def find(self, obj):
        # Compatibility alias
        return self[obj]

    def __iter__(self):
        return iter(self.parents)

    def union(self, *objects):
        roots = [self[x] for x in objects]

        # Preserve legacy behavior:
        # keep the root with the highest weight.
        # In imagepers, earlier / higher-density pixels get larger weights.
        heaviest = max((self.weights[r], r) for r in roots)[1]

        for r in roots:
            if r != heaviest:
                self.parents[r] = heaviest

        return heaviest