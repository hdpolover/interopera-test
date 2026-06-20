"""Narrative generator — LLM-optional.

Stub returns deterministic, firewall-safe text built exclusively from
computed figure values, utilization, status, and limit fields.

Keyless fallback (critical for CI): when api_key is None and no client is
injected, write_narrative() returns the deterministic stub — no network call,
no exception, same output for same inputs.
"""
from __future__ import annotations

import os
from typing import Optional

from src.compute.registry import Figure

# Model override via env var — allows upgrading/swapping without code changes
# when the current model is deprecated or a better option becomes available.
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)


class Narrator:
    """Generate narrative from computed figures.

    LLM path is only activated when api_key is set or an anthropic client is
    injected.  Without a key the stub path is always used.

    The stub is deterministic: identical figures → identical text.
    Every number in the stub is sourced verbatim from a Figure field so the
    firewall never rejects it.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[object] = None,
        driver: Optional[object] = None,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._driver = driver

    def write_narrative(self, figures: list[Figure], firm_id: str) -> str:
        """Generate narrative referencing only figure values from the list.

        If api_key / client is set, delegates to the LLM path (which is
        firewalled downstream).  Otherwise returns the deterministic stub.
        """
        if (self._api_key and self._api_key.strip()) or self._client:
            return self._llm_narrative(figures, firm_id)
        return self._stub_narrative(figures, firm_id)

    # ------------------------------------------------------------------
    # Stub path — deterministic, firewall-safe
    # ------------------------------------------------------------------

    def _stub_narrative(self, figures: list[Figure], firm_id: str) -> str:
        """Deterministic stub built entirely from computed figure fields.

        Every numeric token in the returned string is pulled verbatim from
        a Figure's .value, .utilization, .status, or .limit field, so
        check_firewall() will always pass.
        """
        fig_map = {f.figure: f for f in figures}

        def v(fid: str) -> str:
            """Return the figure's value, or 'N/A' if not present."""
            return fig_map[fid].value if fid in fig_map else "N/A"

        def s(fid: str) -> str:
            """Return status string."""
            return fig_map[fid].status if fid in fig_map else "N/A"

        def lim(fid: str) -> str:
            """Return limit display string."""
            return fig_map[fid].limit if fid in fig_map else "N/A"

        # Identify breaches and at-limit conditions for the summary section.
        # Numeric values used here come from fig.value — all present in figures.
        breach_items = [
            f"{f.figure.replace('_', ' ')} at {f.value}"
            for f in figures
            if f.status == "BREACH"
        ]
        at_limit_items = [
            f"{f.figure.replace('_', ' ')} at {f.value}"
            for f in figures
            if f.status == "AT LIMIT"
        ]

        breach_text = ""
        if breach_items:
            breach_text = (
                "\nBREACH conditions identified:\n"
                + "".join(f"  - {item}\n" for item in breach_items)
            )

        at_limit_text = ""
        if at_limit_items:
            at_limit_text = (
                "\nAT LIMIT conditions:\n"
                + "".join(f"  - {item}\n" for item in at_limit_items)
            )

        # Build the narrative.  All limit strings are taken from fig.limit so
        # the numbers within them are in the computed set.
        return (
            f"Compliance Report Summary — {firm_id.upper()}\n\n"
            f"Asset Allocation:\n"
            f"  Singapore Government Securities: {v('allocation_sgs')}"
            f" (limit {lim('allocation_sgs')}) — {s('allocation_sgs')}\n"
            f"  MAS Bills: {v('allocation_mas_bills')}"
            f" (limit {lim('allocation_mas_bills')}) — {s('allocation_mas_bills')}\n"
            f"  Investment Grade Corporate Bonds: {v('allocation_ig_corp')}"
            f" (limit {lim('allocation_ig_corp')}) — {s('allocation_ig_corp')}\n"
            f"  High Yield Bonds: {v('allocation_high_yield')}"
            f" (limit {lim('allocation_high_yield')}) — {s('allocation_high_yield')}\n"
            f"  Foreign Currency Bonds: {v('allocation_fx_bonds')}"
            f" (limit {lim('allocation_fx_bonds')}) — {s('allocation_fx_bonds')}\n"
            f"  Structured Credit: {v('allocation_structured_credit')}"
            f" (limit {lim('allocation_structured_credit')}) — {s('allocation_structured_credit')}\n"
            f"  Cash: {v('allocation_cash')}"
            f" ({lim('allocation_cash')}) — {s('allocation_cash')}\n\n"
            f"Risk Metrics:\n"
            f"  Non-IG Aggregate Exposure: {v('aggregate_non_ig_exposure')}"
            f" ({lim('aggregate_non_ig_exposure')}) — {s('aggregate_non_ig_exposure')}\n"
            f"  Largest Single Corporate Issuer: {v('largest_single_corporate_issuer')}"
            f" ({lim('largest_single_corporate_issuer')}) — {s('largest_single_corporate_issuer')}\n"
            f"  Largest GRE Issuer: {v('largest_gre_issuer')}"
            f" ({lim('largest_gre_issuer')}) — {s('largest_gre_issuer')}\n"
            f"  Liquid Assets Ratio: {v('liquid_assets_ratio')}"
            f" ({lim('liquid_assets_ratio')}) — {s('liquid_assets_ratio')}\n"
            f"  Portfolio Duration: {v('portfolio_duration')}"
            f" ({lim('portfolio_duration')}) — {s('portfolio_duration')}\n"
            f"  Portfolio DV01: {v('portfolio_dv01')}"
            f" ({lim('portfolio_dv01')}) — {s('portfolio_dv01')}\n"
            f"{breach_text}{at_limit_text}"
        )

    # ------------------------------------------------------------------
    # LLM path — only called when api_key or client is provided
    # ------------------------------------------------------------------

    def _llm_narrative(self, figures: list[Figure], firm_id: str) -> str:
        """Call the Anthropic API.

        The prompt instructs the model to use figure values verbatim and
        introduce NO new numbers.  The returned narrative is firewalled by
        the caller (check_firewall).

        Falls back to the stub if the anthropic package is not installed.
        """
        if self._client is not None:
            client = self._client
        else:
            try:
                import anthropic  # guarded import — package may not be installed
            except ImportError:
                return self._stub_narrative(figures, firm_id)
            client = anthropic.Anthropic(api_key=self._api_key)

        figures_text = "\n".join(
            f"- {f.figure}: value={f.value}, utilization={f.utilization},"
            f" status={f.status}, limit={f.limit}"
            for f in figures
        )

        # Build passage context if a driver was provided (Bonus 3)
        passage_section = ""
        if self._driver is not None:
            try:
                from src.graph.queries import retrieve_passages_for_narrative
                passages = retrieve_passages_for_narrative(self._driver, figures)
                if passages:
                    global_lines = [
                        f"- {p['chunk_id']}: {p['passage_summary']}"
                        for p in passages
                        if p.get("passage_summary")
                    ]
                    local_lines = []
                    for f in figures:
                        citation = getattr(f, "citation", {}) or {}
                        ps = citation.get("passage_summary")
                        page = citation.get("page")
                        if ps:
                            page_str = f" (page {page})" if page is not None else ""
                            local_lines.append(f"- {f.figure}: {ps}{page_str}")
                    parts = []
                    if global_lines:
                        parts.append(
                            "Regulatory basis (from source documents):\n"
                            + "\n".join(global_lines)
                        )
                    if local_lines:
                        parts.append(
                            "Figure-specific citations:\n"
                            + "\n".join(local_lines)
                        )
                    if parts:
                        passage_section = "\n\n" + "\n\n".join(parts)
            except Exception:  # noqa: BLE001 — deliberate fallthrough; passage retrieval is best-effort
                # If retrieval fails, proceed without passages
                pass

        prompt = (
            f"Write a concise compliance report narrative for {firm_id}.\n\n"
            f"RULES (strictly enforced — a firewall will reject any violation):\n"
            f"1. Use ONLY the exact numeric values listed below — do NOT invent, "
            f"   round, derive differences, or alter any number in any way.\n"
            f"2. Do not introduce ANY number that does not appear verbatim in the figures list.\n"
            f"3. Reference figure values and limits verbatim as given.\n"
            f"4. Do NOT include raw chunk IDs, hash strings, or hex identifiers in the narrative.\n"
            f"   Refer to guidelines as 'the fund guidelines' or by section name only.\n"
            f"5. Do NOT compute or mention differences, margins, or distances from limits "
            f"   (e.g. do NOT write '1% below the minimum'). Only state the figure value and status.\n\n"
            f"Figures:\n{figures_text}"
            f"{passage_section}\n\n"
            f"Write the narrative now."
        )
        message = client.messages.create(  # type: ignore[attr-defined]
            model=_ANTHROPIC_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text


def write_narrative(figures: list[Figure], firm_id: str) -> str:
    """Module-level convenience function — always uses the keyless stub path."""
    return Narrator(api_key=None).write_narrative(figures, firm_id=firm_id)
