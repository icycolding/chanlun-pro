import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from chanlun.db import DB


logger = logging.getLogger(__name__)

_AKSHARE_FUTURES_NAME_TO_SYMBOL = {
    "红枣": "CJ",
    "低硫燃料油": "lu",
    "鸡蛋": "JD",
    "豆一": "A",
    "豆二": "B",
    "粳米": "RR",
    "豆粕": "M",
    "PTA": "TA",
    "纯碱": "SA",
    "沪锌": "ZN",
    "苯乙烯": "EB",
    "棕榈": "P",
    "尿素": "UR",
    "玉米": "C",
    "铁矿石": "I",
    "硅铁": "SF",
    "塑料": "L",
    "乙二醇": "EG",
    "聚丙烯": "PP",
    "甲醇": "MA",
    "玻璃": "FG",
    "郑棉": "CF",
    "锡": "SN",
    "液化石油气": "PG",
    "生猪": "LH",
    "PVC": "V",
    "纯苯": "BZ",
    "氧化铝": "AO",
    "镍": "NI",
    "螺纹钢": "RB",
    "橡胶": "RU",
    "对二甲苯": "PX",
    "焦煤": "JM",
    "纸浆": "SP",
    "工业硅": "si",
    "多晶硅": "ps",
    "焦炭": "J",
    "烧碱": "SH",
    "玉米淀粉": "CS",
    "菜油": "OI",
    "碳酸锂": "lc",
    "沪铝": "AL",
    "菜粕": "RM",
    "沪铜": "CU",
    "沪铅": "PB",
    "丁二烯橡胶": "BR",
    "棉纱": "CY",
    "燃油": "FU",
    "不锈钢": "SS",
    "花生": "PK",
    "苹果": "AP",
    "锰硅": "SM",
    "20号胶": "nr",
    "瓶片": "PR",
    "铸造铝合金": "AD",
    "10年期国债": "T",
    "5年期国债": "TF",
    "沪深300": "IF",
    "沥青": "BU",
    "2年期国债": "TS",
    "铂": "pt",
    "30年期国债期货": "TL",
    "沪银": "AG",
    "上证50": "IH",
    "沪金": "AU",
    "短纤": "PF",
    "中证500": "IC",
    "中证1000": "IM",
    "豆油": "Y",
    "白糖": "SR",
    "热卷": "HC",
    "丙烯": "PL",
    "集运指数(欧线)": "ec",
    "胶版印刷纸": "OP",
    "菜籽": "RS",
}
_AKSHARE_FUTURES_SYMBOL_CASE_MAP = {
    symbol.upper(): symbol for symbol in set(_AKSHARE_FUTURES_NAME_TO_SYMBOL.values())
}
_AKSHARE_FUTURES_SYMBOL_TO_NAME = {
    symbol: name for name, symbol in _AKSHARE_FUTURES_NAME_TO_SYMBOL.items()
}
_AKSHARE_FUTURES_ALIAS_TO_SYMBOL = {
    "XAU": "AU",
    "GOLD": "AU",
    "GC": "AU",
    "COMEX GOLD": "AU",
    "黄金": "AU",
    "沪金": "AU",
    "XAG": "AG",
    "SILVER": "AG",
    "白银": "AG",
    "沪银": "AG",
    "COPPER": "CU",
    "HG": "CU",
    "铜": "CU",
    "沪铜": "CU",
    "REBAR": "RB",
    "螺纹": "RB",
    "螺纹钢": "RB",
    "IRON ORE": "I",
    "铁矿": "I",
    "铁矿石": "I",
    "SOYMEAL": "M",
    "豆粕": "M",
    "CORN": "C",
    "玉米": "C",
    "CRUDE OIL": "SC",
    "OIL": "SC",
    "WTI": "SC",
    "BRENT": "SC",
    "CL": "SC",
    "原油": "SC",
    "METHANOL": "MA",
    "甲醇": "MA",
    "CSI300": "IF",
    "沪深300": "IF",
    "CSI500": "IC",
    "中证500": "IC",
    "CSI1000": "IM",
    "中证1000": "IM",
    "SSE50": "IH",
    "上证50": "IH",
    "2Y T-BOND": "TS",
    "5Y T-BOND": "TF",
    "10Y T-BOND": "T",
    "30Y T-BOND": "TL",
    "工业硅": "si",
    "多晶硅": "ps",
    "碳酸锂": "lc",
    "铂": "pt",
    "集运指数(欧线)": "ec",
}
_CFTC_SYMBOL_ALIAS_MAP = {
    "EURUSD": ["EURUSD", "EUR", "欧元", "EURO FX"],
    "GBPUSD": ["GBPUSD", "GBP", "英镑", "BRITISH POUND"],
    "AUDUSD": ["AUDUSD", "AUD", "澳元", "AUSTRALIAN DOLLAR"],
    "NZDUSD": ["NZDUSD", "NZD", "纽元", "NEW ZEALAND DOLLAR"],
    "USDJPY": ["USDJPY", "JPY", "日元", "JAPANESE YEN"],
    "USDCHF": ["USDCHF", "CHF", "瑞郎", "SWISS FRANC"],
    "USDCAD": ["USDCAD", "CAD", "加元", "CANADIAN DOLLAR"],
    "USDCNY": ["USDCNY", "USDCNH", "CNY", "CNH", "人民币", "离岸人民币"],
    "USDCNH": ["USDCNH", "USDCNY", "CNH", "CNY", "人民币", "离岸人民币"],
    "XAU": ["XAU", "AU", "黄金", "GOLD"],
    "XAG": ["XAG", "AG", "白银", "SILVER"],
    "CL": ["CL", "SC", "原油", "CRUDE OIL", "WTI"],
}


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def _safe_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        if hasattr(parsed, "to_pydatetime"):
            parsed = parsed.to_pydatetime()
        if isinstance(parsed, datetime):
            return parsed.replace(tzinfo=None)
    except Exception:
        return None
    return None


def _safe_diff(left: Any, right: Any) -> Optional[float]:
    left_value = _safe_float(left)
    right_value = _safe_float(right)
    if left_value is None or right_value is None:
        return None
    return round(left_value - right_value, 6)


def _normalize_akshare_calendar_date(value: Any) -> str:
    if value is None or value == "":
        return datetime.now().strftime("%Y%m%d")
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if not pd.isna(parsed):
            if hasattr(parsed, "to_pydatetime"):
                parsed = parsed.to_pydatetime()
            if isinstance(parsed, datetime):
                return parsed.strftime("%Y%m%d")
    except Exception:
        pass
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return text


def get_akshare_futures_symbol_name(symbol: Any) -> str:
    exact_symbol = _AKSHARE_FUTURES_SYMBOL_CASE_MAP.get(str(symbol or "").strip().upper(), "")
    return _AKSHARE_FUTURES_SYMBOL_TO_NAME.get(exact_symbol, "")


def normalize_akshare_futures_symbol(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    normalized_candidates: List[str] = []

    def _append(candidate: Any):
        candidate_text = str(candidate or "").strip()
        if candidate_text and candidate_text not in normalized_candidates:
            normalized_candidates.append(candidate_text)

    def _expand(candidate: Any):
        candidate_text = str(candidate or "").strip()
        if not candidate_text:
            return
        _append(candidate_text)
        upper_candidate = candidate_text.upper()
        _append(upper_candidate)
        if "." in upper_candidate:
            parts = [part.strip() for part in upper_candidate.split(".") if part.strip()]
            for part in parts:
                _append(part)
            if parts:
                _append(parts[-1])
        letters_candidate = "".join(re.findall(r"[A-Z]+", upper_candidate))
        if letters_candidate:
            _append(letters_candidate)
            if re.fullmatch(r"[A-Z]+L\d+", letters_candidate):
                _append(re.sub(r"L\d+$", "", letters_candidate))
            stripped_digits = re.sub(r"\d+$", "", letters_candidate)
            _append(stripped_digits)
            if stripped_digits.endswith("L") and len(stripped_digits) > 1:
                _append(stripped_digits[:-1])

    _expand(text)
    compact_text = text.replace("期货", "").replace("主连", "").replace("连续", "").strip()
    _expand(compact_text)

    for candidate in normalized_candidates:
        candidate_text = str(candidate or "").strip()
        if not candidate_text:
            continue
        candidate_variants = [candidate_text]
        upper_candidate = candidate_text.upper()
        candidate_variants.append(upper_candidate)
        letters_candidate = "".join(re.findall(r"[A-Z]+", upper_candidate))
        if letters_candidate:
            candidate_variants.append(letters_candidate)
            if re.fullmatch(r"[A-Z]+L\d+", letters_candidate):
                candidate_variants.append(re.sub(r"L\d+$", "", letters_candidate))
            stripped_digits = re.sub(r"\d+$", "", letters_candidate)
            candidate_variants.append(stripped_digits)
            if stripped_digits.endswith("L") and len(stripped_digits) > 1:
                candidate_variants.append(stripped_digits[:-1])
        for variant in candidate_variants:
            if not variant:
                continue
            if variant in _AKSHARE_FUTURES_NAME_TO_SYMBOL:
                return _AKSHARE_FUTURES_NAME_TO_SYMBOL[variant]
            upper_variant = variant.upper()
            if upper_variant in _AKSHARE_FUTURES_SYMBOL_CASE_MAP:
                return _AKSHARE_FUTURES_SYMBOL_CASE_MAP[upper_variant]
            if upper_variant in _AKSHARE_FUTURES_ALIAS_TO_SYMBOL:
                alias_symbol = _AKSHARE_FUTURES_ALIAS_TO_SYMBOL[upper_variant]
                return _AKSHARE_FUTURES_SYMBOL_CASE_MAP.get(alias_symbol.upper(), alias_symbol)
    return ""


def _build_cftc_symbol_candidates(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    normalized: List[str] = []

    def _append(candidate: Any):
        candidate_text = str(candidate or "").strip()
        if candidate_text and candidate_text not in normalized:
            normalized.append(candidate_text)

    upper_text = text.upper()
    _append(text)
    _append(upper_text)
    alias_candidates = _CFTC_SYMBOL_ALIAS_MAP.get(upper_text, [])
    for candidate in alias_candidates:
        _append(candidate)
        _append(str(candidate).upper())
    if "." in upper_text:
        for part in upper_text.split("."):
            _append(part)
    letters_only = "".join(re.findall(r"[A-Z]+", upper_text))
    if letters_only:
        _append(letters_only)
        stripped_digits = re.sub(r"\d+$", "", letters_only)
        _append(stripped_digits)
    return normalized


def _build_akshare_futures_symbol_candidates(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    normalized: List[str] = []

    def _append(candidate: Any):
        candidate_text = str(candidate or "").strip()
        if candidate_text and candidate_text not in normalized:
            normalized.append(candidate_text)

    exact_symbol = normalize_akshare_futures_symbol(text)
    if exact_symbol:
        _append(exact_symbol)
        symbol_name = get_akshare_futures_symbol_name(exact_symbol)
        if symbol_name:
            _append(symbol_name)

    upper_text = text.upper()
    _append(text)
    _append(upper_text)
    if "." in upper_text:
        for part in upper_text.split("."):
            _append(part)
    letters_only = "".join(re.findall(r"[A-Za-z]+", upper_text))
    if letters_only:
        _append(letters_only)
        stripped_digits = re.sub(r"\d+$", "", letters_only)
        _append(stripped_digits)
        if re.fullmatch(r"[A-Z]+L\d+", letters_only):
            _append(re.sub(r"L\d+$", "", letters_only))
        if stripped_digits.endswith("L") and len(stripped_digits) > 1:
            _append(stripped_digits[:-1])
        _append(letters_only[:2])
    return normalized


class AkshareMarketDataAdapter:
    def __init__(self, ak_module: Any = None, db_instance: Optional[DB] = None):
        self.ak = ak_module
        self.db = db_instance
        if self.ak is None:
            try:
                import akshare as ak

                self.ak = ak
            except ImportError:
                self.ak = None

    @property
    def available(self) -> bool:
        return self.ak is not None

    def _require(self, func_name: str) -> Any:
        if self.ak is None:
            raise RuntimeError("akshare 未安装，无法获取市场数据")
        func = getattr(self.ak, func_name, None)
        if func is None:
            raise AttributeError(f"akshare 缺少接口: {func_name}")
        return func

    def sync_records(self, dataset_type: str, records: List[Dict[str, Any]]) -> int:
        if self.db is None:
            raise RuntimeError("db_instance 未配置，无法同步数据")
        saved = 0
        for item in records or []:
            if dataset_type == "event":
                self.db.market_event_fact_upsert(item)
                saved += 1
            elif dataset_type == "factor":
                self.db.market_factor_snapshot_upsert(item)
                saved += 1
            elif dataset_type == "structure":
                self.db.market_structure_metric_upsert(item)
                saved += 1
            elif dataset_type == "reaction":
                self.db.event_price_reaction_upsert(item)
                saved += 1
            elif dataset_type == "agent_log":
                self.db.agent_inference_log_insert(item)
                saved += 1
        return saved

    def fetch_macro_calendar_events(self, date: str) -> List[Dict[str, Any]]:
        normalized_date = _normalize_akshare_calendar_date(date)
        dataframe = self._require("macro_info_ws")(date=normalized_date)
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.to_dict("records"):
            title = str(row.get("事件") or row.get("事件名称") or row.get("title") or "").strip()
            if not title:
                continue
            event_time = _safe_datetime(row.get("时间") or row.get("日期") or row.get("datetime") or normalized_date)
            region = str(row.get("地区") or row.get("国家") or row.get("region") or "").strip() or None
            actual_value = _safe_float(row.get("今值") or row.get("实际值"))
            forecast_value = _safe_float(row.get("预期值") or row.get("预期"))
            records.append(
                {
                    "event_type": "macro_calendar",
                    "asset_class": "macro",
                    "region": region,
                    "symbol": str(row.get("重要性") or region or "macro"),
                    "title": title,
                    "source_name": "akshare_macro_info_ws",
                    "importance_score": _safe_float(row.get("重要性")) or _safe_float(row.get("重要度")),
                    "actual_value": actual_value,
                    "forecast_value": forecast_value,
                    "previous_value": _safe_float(row.get("前值")),
                    "surprise_value": _safe_diff(actual_value, forecast_value),
                    "published_at": event_time,
                    "effective_at": event_time,
                    "payload": row,
                }
            )
        return records

    def fetch_central_bank_rate_events(self, bank: str) -> List[Dict[str, Any]]:
        bank_map = {
            "federal_reserve": ("macro_bank_usa_interest_rate", "美联储利率决议报告"),
            "ecb": ("macro_bank_euro_interest_rate", "欧洲央行决议报告"),
            "boe": ("macro_bank_english_interest_rate", "英国央行决议报告"),
            "rbnz": ("macro_bank_newzealand_interest_rate", "新西兰联储决议报告"),
            "rba": ("macro_bank_australia_interest_rate", "澳大利亚利率决议报告"),
            "snb": ("macro_bank_switzerland_interest_rate", "瑞士央行决议报告"),
            "boc": ("macro_bank_canada_interest_rate", "加拿大央行决议报告"),
            "boj": ("macro_bank_japan_interest_rate", "日本央行决议报告"),
            "pboc": ("macro_bank_china_interest_rate", "中国央行决议报告"),
        }
        func_name, indicator = bank_map.get(bank, (bank, bank))
        dataframe = self._require(func_name)()
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.to_dict("records"):
            event_time = _safe_datetime(row.get("日期") or row.get("时间"))
            actual_value = _safe_float(row.get("今值") or row.get("当前值"))
            forecast_value = _safe_float(row.get("预测值") or row.get("预期值"))
            records.append(
                {
                    "event_type": "central_bank_rate",
                    "asset_class": "rates",
                    "region": bank,
                    "symbol": bank.upper(),
                    "title": f"{indicator} {row.get('日期') or ''}".strip(),
                    "source_name": "akshare_macro_bank",
                    "actual_value": actual_value,
                    "forecast_value": forecast_value,
                    "previous_value": _safe_float(row.get("前值")),
                    "surprise_value": _safe_diff(actual_value, forecast_value),
                    "published_at": event_time,
                    "effective_at": event_time,
                    "payload": row,
                }
            )
        return records

    def fetch_cftc_snapshots(self, symbol: str) -> List[Dict[str, Any]]:
        dataframe = self._require("macro_usa_cftc_nc_holding")()
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        symbol_candidates = _build_cftc_symbol_candidates(symbol)
        for row in dataframe.tail(20).to_dict("records"):
            as_of_time = _safe_datetime(row.get("日期") or row.get("时间"))
            long_value = None
            short_value = None
            for key, value in row.items():
                key_text = str(key or "").strip()
                upper_key_text = key_text.upper()
                if symbol_candidates and not any(candidate.upper() in upper_key_text for candidate in symbol_candidates):
                    continue
                if "多头" in key_text:
                    long_value = _safe_float(value)
                elif "空头" in key_text:
                    short_value = _safe_float(value)
            if symbol_candidates and long_value is None and short_value is None:
                continue
            net_value = None
            if long_value is not None and short_value is not None:
                net_value = long_value - short_value
            records.append(
                {
                    "factor_group": "positioning",
                    "factor_name": "cftc_net_position",
                    "asset_class": "cross_asset",
                    "symbol": symbol,
                    "tenor": None,
                    "value": net_value,
                    "unit": "contracts",
                    "source_name": "akshare_macro_usa_cftc_nc_holding",
                    "as_of_time": as_of_time or datetime.now(),
                    "metadata": row,
                }
            )
        return records

    def fetch_futures_inventory_snapshots(self, symbol: str) -> List[Dict[str, Any]]:
        fetcher = self._require("futures_inventory_em")
        dataframe = None
        resolved_symbol = str(symbol or "").strip()
        last_error: Optional[Exception] = None
        for candidate in _build_akshare_futures_symbol_candidates(symbol):
            try:
                dataframe = fetcher(symbol=candidate)
                resolved_symbol = candidate
                last_error = None
                break
            except ValueError as e:
                last_error = e
                continue
        if dataframe is None:
            if last_error is not None:
                logger.info(f"AkShare 期货库存暂不支持品种 {symbol}: {str(last_error)}")
            return []
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.tail(20).to_dict("records"):
            as_of_time = _safe_datetime(row.get("日期") or row.get("时间"))
            records.append(
                {
                    "factor_group": "inventory",
                    "factor_name": "inventory_level",
                    "asset_class": "commodity_futures",
                    "symbol": resolved_symbol,
                    "tenor": None,
                    "value": _safe_float(row.get("库存") or row.get("库存量")),
                    "unit": str(row.get("单位") or ""),
                    "change_1d": _safe_float(row.get("增减") or row.get("变化")),
                    "source_name": "akshare_futures_inventory_em",
                    "as_of_time": as_of_time or datetime.now(),
                    "metadata": row,
                }
            )
        return records

    def fetch_futures_basis_snapshots(self, trade_date: str) -> List[Dict[str, Any]]:
        dataframe = self._require("futures_spot_price")(date=trade_date)
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.to_dict("records"):
            symbol = str(row.get("商品") or row.get("symbol") or "").strip()
            if not symbol:
                continue
            as_of_time = _safe_datetime(row.get("日期") or trade_date)
            records.append(
                {
                    "factor_group": "basis",
                    "factor_name": "spot_futures_basis",
                    "asset_class": "commodity_futures",
                    "symbol": symbol,
                    "value": _safe_float(row.get("基差")),
                    "unit": str(row.get("单位") or ""),
                    "source_name": "akshare_futures_spot_price",
                    "as_of_time": as_of_time or datetime.now(),
                    "metadata": row,
                }
            )
            records.append(
                {
                    "factor_group": "basis",
                    "factor_name": "basis_rate",
                    "asset_class": "commodity_futures",
                    "symbol": symbol,
                    "value": _safe_float(row.get("基差率")),
                    "unit": "%",
                    "source_name": "akshare_futures_spot_price",
                    "as_of_time": as_of_time or datetime.now(),
                    "metadata": row,
                }
            )
        return records

    def fetch_stock_profit_forecast_snapshots(self, symbol: str = "") -> List[Dict[str, Any]]:
        dataframe = self._require("stock_profit_forecast_em")(symbol=symbol)
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.head(200).to_dict("records"):
            stock_code = str(row.get("代码") or row.get("证券代码") or "").strip()
            if not stock_code:
                continue
            as_of_time = _safe_datetime(row.get("日期") or datetime.now())
            records.append(
                {
                    "factor_group": "earnings",
                    "factor_name": "eps_forecast",
                    "asset_class": "equity",
                    "symbol": stock_code,
                    "value": _safe_float(row.get("每股收益") or row.get("预测每股收益")),
                    "unit": "cny",
                    "source_name": "akshare_stock_profit_forecast_em",
                    "as_of_time": as_of_time or datetime.now(),
                    "metadata": row,
                }
            )
        return records

    def fetch_stock_fund_flow_snapshots(self, indicator: str = "即时") -> List[Dict[str, Any]]:
        dataframe = self._require("stock_fund_flow_individual")(symbol=indicator)
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.head(200).to_dict("records"):
            stock_code = str(row.get("股票代码") or row.get("代码") or "").strip()
            if not stock_code:
                continue
            as_of_time = _safe_datetime(row.get("更新时间") or row.get("日期") or datetime.now())
            records.append(
                {
                    "factor_group": "fund_flow",
                    "factor_name": "main_net_inflow",
                    "asset_class": "equity",
                    "symbol": stock_code,
                    "value": _safe_float(row.get("主力净流入-净额") or row.get("主力净流入")),
                    "unit": "cny",
                    "source_name": "akshare_stock_fund_flow_individual",
                    "as_of_time": as_of_time or datetime.now(),
                    "metadata": row,
                }
            )
        return records

    def fetch_stock_hsgt_snapshots(self) -> List[Dict[str, Any]]:
        dataframe = self._require("stock_hsgt_fund_flow_summary_em")()
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.tail(60).to_dict("records"):
            as_of_time = _safe_datetime(row.get("交易日") or row.get("日期"))
            records.append(
                {
                    "factor_group": "cross_border_flow",
                    "factor_name": "northbound_net_flow",
                    "asset_class": "equity",
                    "symbol": str(row.get("资金方向") or row.get("板块") or "HSGT"),
                    "value": _safe_float(row.get("成交净买额") or row.get("资金净流入")),
                    "unit": "cny",
                    "source_name": "akshare_stock_hsgt_fund_flow_summary_em",
                    "as_of_time": as_of_time or datetime.now(),
                    "metadata": row,
                }
            )
        return records

    def fetch_stock_repurchase_events(self) -> List[Dict[str, Any]]:
        dataframe = self._require("stock_repurchase_em")()
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.head(200).to_dict("records"):
            stock_code = str(row.get("股票代码") or row.get("代码") or "").strip()
            title = str(row.get("股票简称") or stock_code)
            event_time = _safe_datetime(row.get("最新公告日期") or row.get("公告日期") or datetime.now())
            records.append(
                {
                    "event_type": "share_repurchase",
                    "asset_class": "equity",
                    "region": "cn",
                    "symbol": stock_code,
                    "title": f"{title} 回购",
                    "source_name": "akshare_stock_repurchase_em",
                    "importance_score": _safe_float(row.get("计划回购金额区间-上限")),
                    "published_at": event_time,
                    "effective_at": event_time,
                    "payload": row,
                }
            )
        return records

    def fetch_stock_restricted_release_events(self, symbol: str = "全部股票", start_date: str = "", end_date: str = "") -> List[Dict[str, Any]]:
        dataframe = self._require("stock_restricted_release_summary_em")(symbol=symbol, start_date=start_date, end_date=end_date)
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.to_dict("records"):
            stock_code = str(row.get("股票代码") or row.get("代码") or "").strip()
            event_time = _safe_datetime(row.get("解禁时间") or row.get("日期"))
            records.append(
                {
                    "event_type": "restricted_release",
                    "asset_class": "equity",
                    "region": "cn",
                    "symbol": stock_code,
                    "title": f"{row.get('股票简称') or stock_code} 解禁",
                    "source_name": "akshare_stock_restricted_release_summary_em",
                    "importance_score": _safe_float(row.get("解禁市值")),
                    "published_at": event_time,
                    "effective_at": event_time,
                    "payload": row,
                }
            )
        return records

    def fetch_bond_yield_curve_snapshots(self, symbol: str = "中债国债收益率曲线") -> List[Dict[str, Any]]:
        dataframe = self._require("bond_china_yield")(symbol=symbol)
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.tail(30).to_dict("records"):
            as_of_time = _safe_datetime(row.get("日期") or row.get("date"))
            for tenor in ["2年", "5年", "10年", "30年"]:
                if tenor in row:
                    records.append(
                        {
                            "factor_group": "yield_curve",
                            "factor_name": "yield_curve_point",
                            "asset_class": "rates_futures",
                            "symbol": symbol,
                            "tenor": tenor,
                            "value": _safe_float(row.get(tenor)),
                            "unit": "%",
                            "source_name": "akshare_bond_china_yield",
                            "as_of_time": as_of_time or datetime.now(),
                            "metadata": row,
                        }
                    )
        return records

    def fetch_repo_rate_snapshots(self) -> List[Dict[str, Any]]:
        dataframe = self._require("repo_rate_query")()
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.tail(60).to_dict("records"):
            as_of_time = _safe_datetime(row.get("日期") or row.get("date"))
            records.append(
                {
                    "factor_group": "funding",
                    "factor_name": str(row.get("品种") or "repo_rate"),
                    "asset_class": "rates_futures",
                    "symbol": "CN_REPO",
                    "value": _safe_float(row.get("利率") or row.get("收盘利率")),
                    "unit": "%",
                    "source_name": "akshare_repo_rate_query",
                    "as_of_time": as_of_time or datetime.now(),
                    "metadata": row,
                }
            )
        return records

    def fetch_swap_curve_snapshots(self, symbol: str = "FR007") -> List[Dict[str, Any]]:
        dataframe = self._require("macro_china_swap_rate")()
        records: List[Dict[str, Any]] = []
        if dataframe is None or getattr(dataframe, "empty", True):
            return records
        for row in dataframe.tail(60).to_dict("records"):
            curve_name = str(row.get("曲线名称") or row.get("品种") or symbol)
            if symbol and symbol not in curve_name:
                continue
            as_of_time = _safe_datetime(row.get("日期") or row.get("date"))
            tenor = str(row.get("期限") or row.get("tenor") or "").strip() or None
            records.append(
                {
                    "factor_group": "swap_curve",
                    "factor_name": "swap_rate",
                    "asset_class": "rates_futures",
                    "symbol": curve_name,
                    "tenor": tenor,
                    "value": _safe_float(row.get("利率") or row.get("报价") or row.get("均值")),
                    "unit": "%",
                    "source_name": "akshare_macro_china_swap_rate",
                    "as_of_time": as_of_time or datetime.now(),
                    "metadata": row,
                }
            )
        return records
