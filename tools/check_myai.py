"""Smoke-test the myai package end-to-end."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import numpy as np
import torch

from mahjong_meme.myai.features import encode_state, NUM_PLANES, NUM_SCALARS
from mahjong_meme.myai.model import MyAI, count_parameters
from mahjong_meme.myai.actions import encode_choice


def main() -> int:
    print(f"NUM_PLANES={NUM_PLANES} NUM_SCALARS={NUM_SCALARS}")

    # 1. encoder ----------------------------------------------------------
    state = {
        "actionable": {"kind": "discard", "options": [
            {"action": "discard", "tile": "1m", "slot": 0},
            {"action": "discard", "tile": "5m*", "slot": 4},
        ]},
        "match": {
            "my_seat": 0, "my_server_seat": 0,
            "hand": ["1m", "2m", "3m", "4m", "5m*", "6m", "7m",
                     "8m", "9m", "1p", "2p", "3p", "4p", "5p"],
            "melds": [[], [], [], []],
            "discards": [["3z"], ["1z", "2z"], [], []],
            "liqi": [False, False, False, False],
            "scores": [25000, 24000, 26000, 25000],
            "chang": 0, "ju": 0, "ben": 0,
            "left_tile_count": 66,
            "dora_indicators": ["3z"],
            "last_drawn_tile": "5p",
            "last_discard": None,
        },
    }
    enc = encode_state(state)
    print(f"  planes shape:  {enc['planes'].shape}")
    print(f"  scalars shape: {enc['scalars'].shape}")
    print(f"  mask:          {enc['mask']}")
    assert enc["planes"].shape == (NUM_PLANES, 34)
    assert enc["scalars"].shape == (NUM_SCALARS,)
    assert enc["mask"]["discard"] is True

    # 2. action encoder ---------------------------------------------------
    rec_discard = {
        "event": {"kind": "discard", "actor": 0},
        "state": state,
        "choice": {"action": "discard", "tile": "5m*", "slot": 4},
    }
    lab = encode_choice(rec_discard)
    print(f"  discard choice -> {lab}")
    assert lab == ("discard", 4)  # 5m* -> tile index 4

    # 3. model forward ----------------------------------------------------
    model = MyAI(channels=64, num_blocks=4)
    print(f"  model params (toy): {count_parameters(model):,}")
    planes = torch.from_numpy(enc["planes"]).unsqueeze(0)
    scalars = torch.from_numpy(enc["scalars"]).unsqueeze(0)
    out = model(planes, scalars)
    for head, lg in out.items():
        print(f"    {head}: {tuple(lg.shape)}")
    assert out["discard"].shape == (1, 34)
    assert out["call"].shape == (1, 5)

    # 4. batch test -------------------------------------------------------
    batch_planes = torch.stack([torch.from_numpy(enc["planes"])] * 8)
    batch_scalars = torch.stack([torch.from_numpy(enc["scalars"])] * 8)
    out_b = model(batch_planes, batch_scalars)
    assert out_b["discard"].shape == (8, 34)
    print("  batch forward OK")

    print("\nALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
