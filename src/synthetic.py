"""Deterministic synthetic customer signal list generator."""
from __future__ import annotations
import numpy as np
import pandas as pd

def generate_signals(count: int, seed: int = 20261010, groups: int = 20, redundancy_pairs: int = 0, cable_groups: int = 20) -> pd.DataFrame:
    if count < 0: raise ValueError("count must be nonnegative")
    rng=np.random.default_rng(seed); io=np.array(["AI","AO","DI","DO"])
    frame=pd.DataFrame({"tag":[f"SIG-{i:06d}" for i in range(count)],
                        "io_type":rng.choice(io,size=count),
                        "group":[f"G-{i%max(1,groups):04d}" for i in range(count)],
                        "cable":[f"CBL-{i%max(1,cable_groups):04d}" for i in range(count)],
                        "pair":[i//max(1,cable_groups)+1 for i in range(count)],
                        "redundancy_group":"","redundancy_side":"","previous_location":"","lifecycle":"unwired"})
    for pair in range(min(redundancy_pairs,count//2)):
        a,b=2*pair,2*pair+1; frame.loc[[a,b],"redundancy_group"]=f"RED-{pair:05d}"; frame.loc[a,"redundancy_side"]="A"; frame.loc[b,"redundancy_side"]="B"
    return frame
