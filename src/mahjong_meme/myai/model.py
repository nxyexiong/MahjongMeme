"""MyAI multi-head CNN model.

Topology
--------
Input planes (B, C_planes, 34) are passed through a small ResNet-1D
trunk (1D convolutions along the 34-cell tile axis). Scalar features
(B, S) go through a small MLP. Their fused embedding feeds 5 linear
heads:

    discard  : per-tile head — 34 logits derived from per-position
               trunk activations (NOT pooled, so each tile gets its own
               score).
    call     : 5-class softmax {chi_low, chi_mid, chi_high, pon, pass}.
    kan      : 2-class {kan, pass}.
    riichi   : 2-class {riichi, pass}.
    win      : 2-class {win, pass}.

Parameter counts (default 128 channels, 10 blocks) ~ 1.5M; bump
``channels`` / ``num_blocks`` for bigger runs.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from .features import NUM_PLANES, NUM_SCALARS


class ResBlock1d(nn.Module):
    def __init__(self, ch: int, kernel: int = 3):
        super().__init__()
        pad = kernel // 2
        self.conv1 = nn.Conv1d(ch, ch, kernel, padding=pad)
        self.bn1 = nn.BatchNorm1d(ch)
        self.conv2 = nn.Conv1d(ch, ch, kernel, padding=pad)
        self.bn2 = nn.BatchNorm1d(ch)
        self.act = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.act(self.bn1(self.conv1(x)))
        h = self.bn2(self.conv2(h))
        return self.act(h + x)


class MyAI(nn.Module):
    """Shared CNN trunk + scalar MLP + 5 task heads."""

    def __init__(
        self,
        *,
        channels: int = 128,
        num_blocks: int = 10,
        scalar_emb: int = 64,
        fusion: int = 256,
    ):
        super().__init__()
        self.channels = channels

        self.stem = nn.Conv1d(NUM_PLANES, channels, kernel_size=1)
        self.trunk = nn.Sequential(*[ResBlock1d(channels) for _ in range(num_blocks)])

        self.scalar_mlp = nn.Sequential(
            nn.Linear(NUM_SCALARS, scalar_emb),
            nn.ReLU(inplace=True),
            nn.Linear(scalar_emb, scalar_emb),
            nn.ReLU(inplace=True),
        )

        self.fusion = nn.Sequential(
            nn.Linear(channels + scalar_emb, fusion),
            nn.ReLU(inplace=True),
        )

        # Per-tile discard head: linear projection of trunk activations.
        # We keep the spatial axis (34 tiles) and emit 1 logit per tile.
        # A small scalar bias is injected from `fusion` to give per-state
        # context.
        self.head_discard = nn.Conv1d(channels, 1, kernel_size=1)
        self.head_discard_bias = nn.Linear(fusion, 34)

        # Pooled heads.
        self.head_call = nn.Linear(fusion, 5)
        self.head_kan = nn.Linear(fusion, 2)
        self.head_riichi = nn.Linear(fusion, 2)
        self.head_win = nn.Linear(fusion, 2)

    def forward(
        self,
        planes: torch.Tensor,           # (B, C_planes, 34)
        scalars: torch.Tensor,          # (B, NUM_SCALARS)
    ) -> dict:
        h = self.stem(planes)           # (B, C, 34)
        h = self.trunk(h)               # (B, C, 34)

        pooled = h.mean(dim=-1)         # (B, C)
        s_emb = self.scalar_mlp(scalars)
        fused = self.fusion(torch.cat([pooled, s_emb], dim=-1))  # (B, fusion)

        # Per-tile discard logits + per-state bias.
        disc_per_tile = self.head_discard(h).squeeze(1)          # (B, 34)
        disc_bias = self.head_discard_bias(fused)                # (B, 34)
        logits_discard = disc_per_tile + disc_bias

        return {
            "discard": logits_discard,
            "call":    self.head_call(fused),
            "kan":     self.head_kan(fused),
            "riichi":  self.head_riichi(fused),
            "win":     self.head_win(fused),
        }


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
