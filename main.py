import os
import random
import hmac
import hashlib
import json
import time
import base64

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import uvicorn

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
PAYLOAD_SECRET = os.getenv("PAYLOAD_SECRET", "change-me-in-production")
API_NINJAS_KEY = os.getenv("API_NINJAS_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock this down to your domain in production
    allow_methods=["POST"],
    allow_headers=["*"],
)

# ── Request model ─────────────────────────────────────────────────────────────


class GameRequest(BaseModel):
    auth_id: str
    website: str


# ── Credit score lookup ───────────────────────────────────────────────────────


def get_credit_score(auth_id: str, website: str) -> int:
    response = (
        supabase.table("app_credit_scores")
        .select("scores")
        .eq("auth_id", auth_id)
        .single()
        .execute()
    )
    if not response.data:
        return 450  # default moderate score

    scores: dict = response.data.get("scores")
    print(response.data)
    print(website)
    site_score = scores.get(website)
    print(site_score)
    # print(scores)
    if not site_score:
        return 450

    return site_score  # most recent


# ── Word fetching ─────────────────────────────────────────────────────────────


def fetch_wordsearch_puzzle(grid_size: int, num_words: int) -> dict:
    response = requests.get(
        "https://shadify.yurace.pro/api/wordsearch/generator",
        params={"width": grid_size, "height": grid_size, "wordsCount": num_words},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def fetch_sudoku_puzzle(difficulty: str) -> dict:
    response = requests.get(
        "https://api.api-ninjas.com/v1/sudokugenerate",
        params={"difficulty": difficulty, "width": 3, "height": 3},
        headers={"X-Api-Key": API_NINJAS_KEY},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


# ── Game selection ────────────────────────────────────────────────────────────


def pick_game(credit_score: int) -> dict:
    if credit_score < 500:
        game = random.choice(["wordle", "word_search", "sudoku"])
    elif credit_score < 750:
        game = random.choice(["wordle", "word_search"])
    else:
        game = random.choice(["wordle", "word_search", "meditation"])

    return {"game": game, "config": build_config(game, credit_score)}


def build_config(game: str, credit_score: int) -> dict:
    if game == "wordle":
        if credit_score < 500:
            word_length = 6
        elif credit_score < 700:
            word_length = 5
        else:
            word_length = 4
        random_word = requests.get(
            f"https://random-word-api.herokuapp.com/word?length={word_length}"
        ).json()[0]
        print(random_word)
        return {
            "word": random_word,  # In production, fetch a random word of the correct length from your DB
            "max_guesses": 6,
        }

    if game == "word_search":
        if credit_score < 200:
            grid_size, num_words = 15, 12
        elif credit_score < 500:
            grid_size, num_words = 12, 9
        elif credit_score < 750:
            grid_size, num_words = 10, 7
        else:
            grid_size, num_words = 8, 5
        puzzle = fetch_wordsearch_puzzle(grid_size, num_words)
        return puzzle

    if game == "sudoku":
        difficulty = "expert" if credit_score < 100 else "hard"
        puzzle = fetch_sudoku_puzzle(difficulty)
        return {"difficulty": difficulty, **puzzle}

    if game == "meditation":
        return {"duration_seconds": random.randint(5, 15)}

    return {}


# ── Signed payload ────────────────────────────────────────────────────────────


def sign_payload(data: dict) -> str:
    body = json.dumps(data, separators=(",", ":"))
    body_b64 = base64.urlsafe_b64encode(body.encode()).decode()
    sig = hmac.new(
        PAYLOAD_SECRET.encode(),
        body_b64.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{body_b64}.{sig}"


# ── Route ─────────────────────────────────────────────────────────────────────


@app.post("/game")
def get_game(req: GameRequest):
    try:
        credit_score = get_credit_score(req.auth_id, req.website)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Supabase error: {str(e)}")

    result = pick_game(credit_score)
    payload_data = {
        "game": result["game"],
        "config": result["config"],
        "credit_score": credit_score,
        "auth_id": req.auth_id,
        "website": req.website,
        "ts": int(time.time()),
    }
    return {
        "game": result["game"],
        "payload": sign_payload(payload_data),
    }


if __name__ == "__main__":
    # This replaces the need for "uvicorn main:app" in the terminal
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
