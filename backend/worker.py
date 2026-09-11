import asyncio
import base64
from dataclasses import asdict
from typing import Dict, Any, List, Optional
from modules.data_loader import DataLoader
from modules.optimal_combination import OptimalCombinationFinder
from modules.results_generator import ResultsGenerator
from modules.websocket_notifier import WebSocketNotifier
from modules.logging_manager import logger
from .monitor import SystemMonitor
import time
import io

from modules.utils import clean_column_name

class Worker:
    def __init__(self):
        self.data_loader = DataLoader()
        self.finder = OptimalCombinationFinder()
        self.notifier = WebSocketNotifier()

    async def process_file(
        self,
        file_content: bytes,
        filename: str,
        degree: int,
        target_col: str,
        avaliando: Optional[Dict[str, float]] = None,
        grau_item1: int = 1,
        grau_item3: int = 1,
        candidate_cols: Optional[List[str]] = None,
        solicitante: str = "",
        finalidade: str = "",
    ):
        """
        Processes an uploaded file and finds the best model.
        """
        start_time = time.time()
        try:
            # 1. Load Data
            await self.notifier.send_notification({"status": "loading_data", "progress": 0.1})
            load_result = self.data_loader.load_data(file_content, filename)

            if not load_result.success:
                await self.notifier.send_notification({"status": "error", "message": load_result.message})
                return

            df = load_result.dataframe

            # Clean target column name to match loaded data
            target_col = clean_column_name(target_col)

            # 1b. Expand the user's requested candidate columns to match the
            # ACTUAL df.columns. A categorical column the user picked (e.g.
            # "bairro") no longer exists as-is in df: data_loader one-hot
            # encoded it into "bairro_centro", "bairro_sul", ... and dropped
            # the original (see modules/data_loader.py). Without this
            # expansion, every categorical column the user selects would
            # silently vanish from the search (find_best_model only logs a
            # warning server-side for names it can't find) - defeating the
            # "no rigid pre-selection" goal and leaving the user in the dark.
            # A name that still can't be resolved after this is reported to
            # the user via candidate_warnings below (never silent).
            # original_cols: the set of raw column names BEFORE one-hot
            # encoding (data_loader keeps original_df around for this).
            # Used both to expand requested candidate columns below and to
            # keep pure one-hot dummy columns (e.g. "bairro_centro") out of
            # market_summary, which must only report real market variables.
            original_cols = (
                set(self.data_loader.original_df.columns)
                if self.data_loader.original_df is not None else set()
            )

            candidate_warnings: List[str] = []
            if candidate_cols is not None:
                df_cols = set(df.columns)
                expanded: List[str] = []
                for c in candidate_cols:
                    if c in df_cols:
                        expanded.append(c)
                        continue
                    # Guarded prefix match against the one-hot dummy columns
                    # for this base variable only: excludes any df column
                    # that is itself an original raw column name, OR a dummy
                    # of a DIFFERENT (longer) original categorical column
                    # (e.g. a genuine "area_util" column, or dummies of
                    # "padrao_acabamento", must never be swallowed by a
                    # request for "area" / "padrao").
                    dummies = [
                        d for d in df_cols
                        if d.startswith(f"{c}_") and d not in original_cols
                        and not any(
                            d.startswith(f"{o}_") for o in original_cols
                            if o != c and len(o) > len(c)
                        )
                    ]
                    if dummies:
                        expanded.extend(dummies)
                    else:
                        reason = load_result.excluded_columns.get(c)
                        if reason:
                            candidate_warnings.append(
                                f"Coluna '{c}' solicitada como candidata não pôde ser "
                                f"usada no modelo: {reason}"
                            )
                        else:
                            candidate_warnings.append(
                                f"Coluna '{c}' solicitada como candidata não foi "
                                f"encontrada nos dados processados."
                            )
                candidate_cols = expanded

            # 2. Find Optimal Combination
            # find_best_model is synchronous and CPU-bound (OLS fits, Cook's
            # distance, VIF per column, potentially tens of thousands of
            # candidates). Running it inline on the event loop would block
            # every other websocket connection and request this process is
            # serving for the whole duration of the search, so it is
            # offloaded to a worker thread. generate_charts (matplotlib
            # pyplot global state) and generate_pdf_report are NOT offloaded
            # here - they stay on the event loop.
            await self.notifier.send_notification({"status": "finding_model", "progress": 0.3})
            optimal_result = await asyncio.to_thread(
                self.finder.find_best_model,
                df, target_col, degree,
                avaliando_raw=avaliando, grau_item1=grau_item1, grau_item3=grau_item3,
                candidate_cols=candidate_cols,
            )

            if not optimal_result.success or not optimal_result.best_model:
                 await self.notifier.send_notification({"status": "error", "message": "Could not find a valid model."})
                 return

            # 3. Generate Results
            await self.notifier.send_notification({"status": "generating_report", "progress": 0.8})
            charts = ResultsGenerator.generate_charts(optimal_result.best_model)

            # 3a. Diagnóstico do Mercado (NBR 14653-2 §10.1-f): n + min/mean/max
            # for each BASE variable actually used in the winning model (not
            # every candidate offered - only the ones the search picked),
            # derived from the transformed column names in the winner's
            # coefficients (e.g. "ln(area)" -> base variable "area"). Pure
            # one-hot dummy columns (e.g. "bairro_centro", a 0/1 indicator
            # with no market-quantity meaning) are excluded from this
            # section: a real base variable must be in BOTH df (survived
            # into the model) and original_cols (it existed, untransformed,
            # in the raw data) - a dummy fails the second test.
            base_vars_used: list = []
            for col in (optimal_result.best_model.coefficients or {}).keys():
                if col == "const":
                    continue
                base = self.finder._base_name(col)
                if base not in base_vars_used:
                    base_vars_used.append(base)
            market_vars = [
                b for b in base_vars_used if b in df.columns and b in original_cols
            ]
            market_summary = (
                ResultsGenerator.build_market_summary(df, variable_cols=market_vars)
                if market_vars else None
            )

            # 3b. Generate PDF report (NBR 14653-2 §10.2 laudo simplificado)
            # Reuse the charts already generated above instead of paying for
            # generate_charts() a second time inside generate_pdf_report.
            pdf_bytes = ResultsGenerator.generate_pdf_report(
                optimal_result.best_model,
                target_col=target_col,
                avaliando_raw=avaliando,
                solicitante=solicitante,
                finalidade=finalidade,
                exhaustive=optimal_result.exhaustive,
                combinations_tested=optimal_result.combinations_tested,
                search_message=optimal_result.message,
                market_summary=market_summary,
                charts=charts,
            )
            report_pdf_base64 = (
                base64.b64encode(pdf_bytes).decode("utf-8") if pdf_bytes else None
            )

            # 4. Final Response
            validation_result = optimal_result.best_model.validation_result
            validation_dict = {}
            if validation_result:
                validation_dict = {**validation_result.__dict__}
                validation_dict["item_scores"] = [asdict(i) for i in validation_result.item_scores]

            response = {
                "status": "completed",
                "progress": 1.0,
                "model_metrics": optimal_result.best_model.model_metrics.__dict__,
                "formula": optimal_result.best_model.formula,
                "charts": charts,
                "validation": validation_dict,
                "target_achieved": optimal_result.target_achieved,
                "best_grau_reached": optimal_result.best_grau_reached,
                "report_pdf_base64": report_pdf_base64,
                # Transparência metodológica (Anexo A): whether the search
                # was truly exhaustive over the full transformation x
                # inclusion space, or degraded to the top-N-correlation
                # fallback heuristic (OptimalCombinationFinder docstring) -
                # previously tracked internally and logged but never
                # reaching the user through this response.
                "exhaustive": optimal_result.exhaustive,
                "combinations_tested": optimal_result.combinations_tested,
                "search_message": optimal_result.message,
                # Warnings about columns from the user's spreadsheet that
                # could not technically become model variables (see
                # modules/data_loader.py DataLoadResult.excluded_columns) -
                # the user must never be left silently in the dark about a
                # column they brought in that didn't make it into the model.
                # General validation warnings (e.g. sample size), EXCLUDING
                # the per-column exclusion messages already surfaced
                # structured below as "excluded_columns" - avoids showing
                # the same exclusion to the user twice (once as st.info per
                # column, once as a raw st.warning string here).
                "data_warnings": (
                    [
                        w for w in load_result.validation.warnings
                        if w not in {
                            f"Coluna '{col}' excluída da modelagem: {reason}"
                            for col, reason in (load_result.excluded_columns or {}).items()
                        }
                    ] if load_result.validation else []
                ),
                # Column -> reason it could not technically become a model
                # variable (data_loader.py). Structured, so the frontend can
                # render one message per column instead of parsing text.
                "excluded_columns": load_result.excluded_columns or {},
                # Columns the user explicitly requested as candidates that
                # could not be resolved to any actual model column (typo,
                # or a name that matches an excluded_columns entry above).
                "candidate_warnings": candidate_warnings,
            }

            await self.notifier.send_notification(response)
            SystemMonitor.log_performance("process_file", start_time)

        except Exception as e:
            logger.error(f"Worker error: {str(e)}")
            await self.notifier.send_notification({"status": "error", "message": str(e)})
