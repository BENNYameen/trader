"""Logistic regression (L2), standard library only: probability that NIFTY is higher at the exit
time than at the decision. Features are standardized with the training rows' own mean and
spread, so nothing from the test days leaks in."""

import math


class Logit(object):
    def __init__(self, l2=1e-3, lr=0.1, epochs=300):
        self.l2, self.lr, self.epochs = l2, lr, epochs
        self.w, self.b, self.mu, self.sd = None, 0.0, None, None

    def fit(self, X, y):
        n, m = len(X), len(X[0])
        self.mu = [sum(r[j] for r in X) / n for j in range(m)]
        self.sd = [max(1e-9, (sum((r[j] - self.mu[j]) ** 2 for r in X) / n) ** 0.5) for j in range(m)]
        Z = [[(r[j] - self.mu[j]) / self.sd[j] for j in range(m)] for r in X]
        w, b = [0.0] * m, 0.0
        for _ in range(self.epochs):
            gw, gb = [0.0] * m, 0.0
            for z, t in zip(Z, y):
                p = _sig(b + sum(wj * zj for wj, zj in zip(w, z)))
                e = p - t
                gb += e
                for j in range(m):
                    gw[j] += e * z[j]
            b -= self.lr * gb / n
            w = [wj - self.lr * (g / n + self.l2 * wj) for wj, g in zip(w, gw)]
        self.w, self.b = w, b
        return self

    def prob(self, x):
        z = [(xj - mu) / sd for xj, mu, sd in zip(x, self.mu, self.sd)]
        return _sig(self.b + sum(wj * zj for wj, zj in zip(self.w, z)))


def _sig(v):
    if v >= 0:
        return 1.0 / (1.0 + math.exp(-v))
    e = math.exp(v)
    return e / (1.0 + e)
