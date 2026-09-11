import json
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from .websocket import router as websocket_router
from .worker import Worker
from modules.config_manager import config
from modules.logging_manager import logger
from modules.utils import clean_column_name
import uvicorn

app = FastAPI(
    title=config.APP_NAME,
    description="API for CONFENGE MODELA PRO",
    version="0.1.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, specify domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(websocket_router)

worker = Worker()

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    degree: int = Form(...),
    target_col: str = Form(...),
    avaliando_json: str = Form(None),
    grau_item1: int = Form(1),
    grau_item3: int = Form(1),
    candidate_cols_json: str = Form(None),
    solicitante: str = Form(""),
    finalidade: str = Form(""),
):
    """
    Endpoint to upload file and start processing.
    """
    try:
        contents = await file.read()
        filename = file.filename

        # Parse the avaliando's characteristics, if provided, and clean the
        # keys so they match the already-cleaned column names used downstream.
        avaliando = None
        if avaliando_json:
            try:
                raw_avaliando = json.loads(avaliando_json)
                avaliando = {
                    clean_column_name(str(k)): v for k, v in raw_avaliando.items()
                }
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                logger.warning(f"Invalid avaliando_json, ignoring: {str(e)}")
                avaliando = None

        # Parse the user's free choice of candidate variable columns, if
        # provided, cleaning each name the same way target_col and
        # avaliando's keys are cleaned so they match df.columns downstream.
        # No pre-selection or limit is enforced here: any list the user
        # sends (any size, any column) is honored as-is.
        candidate_cols = None
        if candidate_cols_json:
            try:
                raw_candidate_cols = json.loads(candidate_cols_json)
                if isinstance(raw_candidate_cols, list):
                    candidate_cols = [
                        clean_column_name(str(c)) for c in raw_candidate_cols
                    ]
                else:
                    logger.warning(
                        f"candidate_cols_json is not a list, ignoring: {raw_candidate_cols!r}"
                    )
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Invalid candidate_cols_json, ignoring: {str(e)}")
                candidate_cols = None

        # Start processing in background
        background_tasks.add_task(
            worker.process_file,
            contents,
            filename,
            degree,
            target_col,
            avaliando,
            grau_item1,
            grau_item3,
            candidate_cols=candidate_cols,
            solicitante=solicitante,
            finalidade=finalidade,
        )

        return {"message": "File uploaded successfully. Processing started.", "filename": filename}

    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        return {"error": str(e)}

def main():
    uvicorn.run(
        "backend.api:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.DEBUG
    )

if __name__ == "__main__":
    main()
