from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.benchmark_cache import (
    git_rev_parse,
    tracepack_meta_path,
    validate_cached_tracepack_assets,
)
from app.benchmark_context import (
    analysis_sidecar_path,
    compare_sidecar_candidates,
    intent_sidecar_path,
    load_json as load_json_file,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve_path(path_value: str) -> Path:
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    return path


def _rel_to_outputs(path: Path, *, outputs_root: Path) -> str | None:
    try:
        return path.resolve().relative_to(outputs_root.resolve()).as_posix()
    except ValueError:
        return None


def _rewrite_prefixed_path(
    value: Any,
    *,
    source_root: Path,
    target_root: Path,
    outputs_root: Path,
) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    outputs_root = outputs_root.resolve()
    source_rel = _rel_to_outputs(source_root, outputs_root=outputs_root)
    target_rel = _rel_to_outputs(target_root, outputs_root=outputs_root)

    raw_path = Path(token)
    if raw_path.is_absolute():
        try:
            suffix = raw_path.resolve().relative_to(source_root)
        except ValueError:
            return token
        return str((target_root / suffix).resolve())

    if source_rel and target_rel and token == source_rel:
        return target_rel
    if source_rel and target_rel and token.startswith(source_rel + "/"):
        return target_rel + token[len(source_rel) :]
    return token


def _rewrite_tracepack_payload(
    payload: dict[str, Any],
    *,
    source_root: Path,
    target_root: Path,
    outputs_root: Path,
) -> dict[str, Any]:
    out = json.loads(json.dumps(payload))
    out["trace_root_path"] = str(target_root.resolve())
    out["trace_root_rel"] = _rel_to_outputs(target_root, outputs_root=outputs_root)
    for collection_name in ("run_index", "records"):
        entries = out.get(collection_name)
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            for key in (
                "trace_path",
                "trace_rel_path",
                "trace_preview_path",
                "trace_preview_rel_path",
            ):
                rewritten = _rewrite_prefixed_path(
                    item.get(key),
                    source_root=source_root,
                    target_root=target_root,
                    outputs_root=outputs_root,
                )
                if rewritten is not None:
                    item[key] = rewritten
    return out


def _add_promotion_block(payload: dict[str, Any], *, source_commit: str, target_commit: str, target_ref: str) -> dict[str, Any]:
    out = json.loads(json.dumps(payload))
    promotion = dict(out.get("promotion") or {})
    promotion.update(
        {
            "promoted_at_utc": datetime.now(timezone.utc).isoformat(),
            "promoted_from_commit": source_commit,
            "promoted_to_commit": target_commit,
            "target_ref": target_ref,
        }
    )
    out["promotion"] = promotion
    return out


def promote_cache(
    *,
    candidate_json_path: Path,
    target_ref: str,
) -> dict[str, Path]:
    candidate_json_path = candidate_json_path.resolve()
    if not candidate_json_path.exists():
        raise SystemExit(f"Candidate benchmark JSON not found: {candidate_json_path}")

    source_commit = candidate_json_path.parent.name
    target_commit = git_rev_parse(target_ref)
    if source_commit == target_commit:
        return {"candidate_json": candidate_json_path}

    results_root = candidate_json_path.parent.parent.resolve()
    outputs_root = results_root.parent.resolve()
    target_dir = (results_root / target_commit).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_json = (target_dir / candidate_json_path.name).resolve()
    target_meta = tracepack_meta_path(target_json)
    if target_json.exists() or target_meta.exists():
        raise SystemExit(
            f"Target cache already exists for {target_commit}: {target_json.name}"
        )

    source_payload = load_json_file(candidate_json_path)
    source_trace_root = Path(
        str(source_payload.get("trace_root_path") or "")
    ).expanduser()
    if not source_trace_root.is_absolute():
        source_trace_root = (outputs_root / source_payload["trace_root_rel"]).resolve()
    target_trace_root = target_json.with_suffix("")
    shutil.copytree(source_trace_root, target_trace_root)

    promoted_payload = _rewrite_tracepack_payload(
        source_payload,
        source_root=source_trace_root,
        target_root=target_trace_root,
        outputs_root=outputs_root,
    )
    promoted_payload = _add_promotion_block(
        promoted_payload,
        source_commit=source_commit,
        target_commit=target_commit,
        target_ref=target_ref,
    )
    target_json.write_text(
        json.dumps(promoted_payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    source_meta = tracepack_meta_path(candidate_json_path)
    if source_meta.exists():
        meta_payload = load_json_file(source_meta)
        meta_payload["commit"] = target_commit
        meta_payload["json_path"] = str(target_json)
        meta_payload = _add_promotion_block(
            meta_payload,
            source_commit=source_commit,
            target_commit=target_commit,
            target_ref=target_ref,
        )
        target_meta.write_text(
            json.dumps(meta_payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    sidecars = [
        intent_sidecar_path(candidate_json_path),
        analysis_sidecar_path(candidate_json_path),
        candidate_json_path.with_name(f"{candidate_json_path.stem}.inspect.json"),
    ]
    promoted_paths: dict[str, Path] = {
        "candidate_json": target_json,
        "candidate_meta": target_meta,
    }
    for sidecar in sidecars:
        if not sidecar.exists():
            continue
        target_sidecar = target_dir / sidecar.name
        payload = load_json_file(sidecar)
        payload = _add_promotion_block(
            payload,
            source_commit=source_commit,
            target_commit=target_commit,
            target_ref=target_ref,
        )
        outputs = dict(payload.get("outputs") or {})
        if outputs:
            if "candidate_commit" in outputs:
                outputs["candidate_commit"] = target_commit
            if "candidate_json" in outputs:
                outputs["candidate_json"] = str(target_json)
            if sidecar.name.endswith(".intent.json"):
                outputs["intent_json"] = str(target_sidecar)
            if sidecar.name.endswith(".analysis.json"):
                outputs["analysis_json"] = str(target_sidecar)
            payload["outputs"] = outputs
        if "candidate_json" in payload:
            payload["candidate_json"] = str(target_json)
        target_sidecar.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        promoted_paths[target_sidecar.stem.split(".")[-1]] = target_sidecar

    for compare_path in compare_sidecar_candidates(candidate_json_path):
        target_compare = target_dir / compare_path.name
        compare_payload = load_json_file(compare_path)
        compare_payload["candidate_commit"] = target_commit
        compare_payload = _add_promotion_block(
            compare_payload,
            source_commit=source_commit,
            target_commit=target_commit,
            target_ref=target_ref,
        )
        target_compare.write_text(
            json.dumps(compare_payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        promoted_paths.setdefault("compare_json", target_compare)

    cache_issue = validate_cached_tracepack_assets(
        target_json,
        outputs_root=outputs_root,
    )
    if cache_issue is not None:
        raise SystemExit(f"Promoted cache is incomplete: {cache_issue}")
    return promoted_paths


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Promote a dirty benchmark cache into a clean commit cache key"
    )
    ap.add_argument("--candidate-json", required=True)
    ap.add_argument("--target-ref", required=True)
    return ap


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    result = promote_cache(
        candidate_json_path=_resolve_path(args.candidate_json),
        target_ref=str(args.target_ref),
    )
    print("# promote")
    print(f"candidate_json={result['candidate_json']}")
    candidate_meta = result.get("candidate_meta")
    if candidate_meta is not None:
        print(f"candidate_meta={candidate_meta}")
    compare_json = result.get("compare_json")
    if compare_json is not None:
        print(f"compare_json={compare_json}")


__all__ = ["build_parser", "main", "promote_cache"]


if __name__ == "__main__":
    main()
