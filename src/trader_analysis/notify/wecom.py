from __future__ import annotations

from dataclasses import dataclass

import requests

from trader_analysis.signals.types import Signal


@dataclass
class WeComWebhookNotifier:
    webhook_url: str
    timeout_s: float = 5.0

    def _render_markdown(self, signals: list[Signal]) -> str:
        lines = ["## TraderAnalysis Signal Alert", ""]
        for s in signals:
            lines.append(
                f"- `{s.timestamp}` `{s.symbol}` **{s.signal.value}** strength={s.strength:.2f} reason={s.reason}"
            )
        return "\n".join(lines)

    def send(self, signals: list[Signal]) -> None:
        if not signals:
            return
        payload = {"msgtype": "markdown", "markdown": {"content": self._render_markdown(signals)}}
        resp = requests.post(self.webhook_url, json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
