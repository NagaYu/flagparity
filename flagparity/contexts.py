"""The fixed synthetic context set (DECISIONS.md D-6, reused by P1-C-4). Part of the asset, not an input."""
N = 1000


def d6_keys():
    return ["user-%04d" % i for i in range(N)]


DESCRIPTION = ("D-6: N=1000, targetingKey user-0000..user-0999; every attribute an allocation's bucketing "
               "expression references is set to the targetingKey string; no other attributes.")
