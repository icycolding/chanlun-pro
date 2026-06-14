#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, List


def build_theme_ontology(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    entities: List[Dict[str, Any]],
    propagation_chain: List[Dict[str, Any]],
    actor_profiles: List[Dict[str, Any]] | None = None,
    cross_asset_signals: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    theme_id = f"theme:{theme_definition.get('id') or 'custom'}"
    theme_label = str(theme_definition.get("label") or "自定义主题")
    nodes.append(
        {
            "id": theme_id,
            "type": "Theme",
            "label": theme_label,
            "description": str(theme_definition.get("description") or ""),
        }
    )

    asset_name = str(asset_context.get("asset_name") or asset_context.get("current_code") or "").strip()
    asset_id = ""
    if asset_name:
        asset_id = f"asset:{asset_context.get('current_code') or asset_name}"
        nodes.append(
            {
                "id": asset_id,
                "type": "Asset",
                "label": asset_name,
                "description": "当前推演资产",
            }
        )
        edges.append(
            {
                "source": theme_id,
                "target": asset_id,
                "relation": "impacts",
                "summary": f"{theme_label} 对 {asset_name} 产生定价影响。",
            }
        )
        price_direction = str(asset_context.get("price_direction") or "neutral")
        latest_change_pct = asset_context.get("latest_change_pct", 0.0)
        market_signal_id = f"signal:{asset_context.get('current_code') or asset_name}"
        nodes.append(
            {
                "id": market_signal_id,
                "type": "MarketSignal",
                "label": f"价格状态:{price_direction}",
                "description": f"当前价格变化 {latest_change_pct:+.3f}%",
            }
        )
        edges.append(
            {
                "source": asset_id,
                "target": market_signal_id,
                "relation": "shows",
                "summary": f"{asset_name} 当前价格状态为 {price_direction}。",
            }
        )

    for index, entity in enumerate(entities or []):
        entity_name = str(entity.get("name") or "").strip()
        if not entity_name:
            continue
        entity_id = f"entity:{index}:{entity_name}"
        nodes.append(
            {
                "id": entity_id,
                "type": str(entity.get("entity_type") or "Entity"),
                "label": entity_name,
                "description": str(entity.get("summary") or ""),
            }
        )
        edges.append(
            {
                "source": theme_id,
                "target": entity_id,
                "relation": "contains",
                "summary": str(entity.get("role") or "主题相关实体"),
            }
        )

    for index, actor in enumerate(actor_profiles or []):
        actor_name = str(actor.get("name") or "").strip()
        if not actor_name:
            continue
        actor_id = f"actor:{index}:{actor_name}"
        nodes.append(
            {
                "id": actor_id,
                "type": str(actor.get("actor_type") or "Actor"),
                "label": actor_name,
                "description": str(actor.get("summary") or actor.get("role") or ""),
            }
        )
        edges.append(
            {
                "source": theme_id,
                "target": actor_id,
                "relation": "driven_by",
                "summary": str(actor.get("role") or "主题相关主体"),
            }
        )
        if asset_id:
            edges.append(
                {
                    "source": actor_id,
                    "target": asset_id,
                    "relation": "influences",
                    "summary": str(actor.get("stance") or "影响目标资产定价"),
                }
            )

    for index, cross_asset in enumerate(cross_asset_signals or []):
        cross_asset_name = str(cross_asset.get("name") or cross_asset.get("code") or "").strip()
        if not cross_asset_name:
            continue
        cross_asset_id = f"cross_asset:{index}:{cross_asset_name}"
        nodes.append(
            {
                "id": cross_asset_id,
                "type": "CrossAsset",
                "label": cross_asset_name,
                "description": str(cross_asset.get("summary") or ""),
            }
        )
        if asset_id:
            edges.append(
                {
                    "source": asset_id,
                    "target": cross_asset_id,
                    "relation": "resonates_with",
                    "summary": str(cross_asset.get("alignment_label") or "跨资产共振"),
                }
            )

    for index, step in enumerate(propagation_chain or []):
        stage = str(step.get("stage") or f"阶段{index + 1}")
        node_id = f"stage:{index + 1}"
        nodes.append(
            {
                "id": node_id,
                "type": "PropagationStage",
                "label": stage,
                "description": str(step.get("summary") or ""),
            }
        )
        edges.append(
            {
                "source": theme_id if index == 0 else f"stage:{index}",
                "target": node_id,
                "relation": "propagates_to",
                "summary": str(step.get("summary") or ""),
            }
        )

    return {
        "theme": theme_definition,
        "nodes": nodes,
        "edges": edges,
        "entity_count": len(nodes),
        "relation_count": len(edges),
    }
