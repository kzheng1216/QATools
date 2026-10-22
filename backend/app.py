#!/usr/bin/env python3
from __future__ import annotations

import uvicorn
from conf.config import config
from controllers import api_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app():
    my_app = FastAPI()
    register_router(my_app)
    register_middleware(my_app)
    return my_app


def register_router(my_app: FastAPI):
    my_app.include_router(api_router)


def register_middleware(my_app: FastAPI):
    my_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # allow all origins
        allow_credentials=True,
        allow_methods=["*"],  # allow all methods
        allow_headers=["*"],  # allow all headers
    )


app = create_app()

# Start up with cmd: uvicorn app:app --host 0.0.0.0 --port 9888
if __name__ == "__main__":
    uvicorn.run("app:app", host=config.host, port=config.port, reload=True, debug=True)
