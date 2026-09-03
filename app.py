import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import os
import uuid
import sqlite3
import base64
import asyncio
import sys
import io
import re
import traceback

from dotenv import load_dotenv, dotenv_values

# ---------------------------------------------------------
# AUDIO
# ---------------------------------------------------------
from gtts import gTTS

# ---------------------------------------------------------
# GEMINI
# ---------------------------------------------------------
from google import genai
from google.genai import types

# ---------------------------------------------------------
# PATH CONFIGURATION
# ---------------------------------------------------------
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

ENV_FILE = BASE_DIR / ".env"

DB_PATH = BASE_DIR / "appointments_poc.db"

FRONTEND_FILE = BASE_DIR / "frontend.html"


# ---------------------------------------------------------
# LOAD ENVIRONMENT VARIABLES
# ---------------------------------------------------------
load_dotenv(ENV_FILE)

env_values = dotenv_values(ENV_FILE)

print("======================================")
print("ENVIRONMENT CONFIGURATION")
print("======================================")
print("ENV FILE:", ENV_FILE)
print("ENV EXISTS:", ENV_FILE.exists())
print("VARIABLES FOUND:", list(env_values.keys()))
print("GEMINI KEY FOUND:", "GEMINI_API_KEY" in env_values)
print("DATABASE:", DB_PATH)
print("======================================")


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
MODEL_NAME = "gemini-2.5-flash"

GEMINI_CLIENT = None


# ---------------------------------------------------------
# WINDOWS ASYNCIO
# ---------------------------------------------------------
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )


# ---------------------------------------------------------
# FASTAPI
# ---------------------------------------------------------
app = FastAPI(
    title="Apollo Hospital Appointment Agent"
)


# =========================================================
# DATABASE
# =========================================================

def get_db_connection():
    """
    Create SQLite database connection.
    """

    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=10
    )

    return conn


def init_db():

    print("\nInitializing database...")

    conn = get_db_connection()

    cursor = conn.cursor()

    # -----------------------------------------------------
    # Doctors table
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            specialty TEXT
        )
        """
    )

    # -----------------------------------------------------
    # Appointments table
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            doctor_name TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            patient_email TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(doctor_name, appointment_time)
        )
        """
    )

    # -----------------------------------------------------
    # Insert doctors
    # -----------------------------------------------------

    doctors = [
        ("Dr. Meera Patel", "Cardiology"),
        ("Dr. Arjun Rao", "Neurology")
    ]

    for doctor_name, specialty in doctors:

        cursor.execute(
            """
            INSERT OR IGNORE INTO doctors
            (name, specialty)
            VALUES (?, ?)
            """,
            (
                doctor_name,
                specialty
            )
        )

    conn.commit()

    conn.close()

    print("✅ Database initialized successfully.")


# Initialize database
init_db()


# =========================================================
# APPOINTMENT TOOLS
# =========================================================

def list_doctors_tool() -> dict:

    """
    Return all available doctors.
    """

    print("\n🔧 TOOL: list_doctors")

    conn = get_db_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT name, specialty
            FROM doctors
            ORDER BY name
            """
        )

        rows = cursor.fetchall()

        doctors = []

        for row in rows:

            doctors.append(
                {
                    "name": row[0],
                    "specialty": row[1]
                }
            )

        print("Doctors:", doctors)

        return {
            "success": True,
            "doctors": doctors
        }

    except Exception as e:

        print("❌ list_doctors error:", str(e))

        return {
            "success": False,
            "error": str(e)
        }

    finally:

        conn.close()


# ---------------------------------------------------------
# CHECK SLOT
# ---------------------------------------------------------

def check_slot_tool(
    doctor_name: str,
    appointment_time: str
) -> dict:

    """
    Check whether a doctor/time combination is available.
    """

    print("\n🔧 TOOL: check_slot")

    print("Doctor:", doctor_name)
    print("Appointment time:", appointment_time)

    conn = get_db_connection()

    try:

        cursor = conn.cursor()

        # First check doctor exists
        cursor.execute(
            """
            SELECT id
            FROM doctors
            WHERE name = ?
            """,
            (doctor_name,)
        )

        doctor = cursor.fetchone()

        if not doctor:

            print("❌ Doctor not found")

            return {
                "success": False,
                "status": "doctor_not_found",
                "message": "Doctor does not exist."
            }

        # Check appointment
        cursor.execute(
            """
            SELECT id, patient_name, status
            FROM appointments
            WHERE doctor_name = ?
            AND appointment_time = ?
            """,
            (
                doctor_name,
                appointment_time
            )
        )

        appointment = cursor.fetchone()

        if appointment:

            print("❌ Slot already booked")

            return {
                "success": True,
                "status": "booked",
                "message": "This appointment slot is already booked."
            }

        print("✅ Slot available")

        return {
            "success": True,
            "status": "available",
            "message": "This appointment slot is available."
        }

    except Exception as e:

        print("❌ check_slot error:", str(e))

        return {
            "success": False,
            "status": "error",
            "error": str(e)
        }

    finally:

        conn.close()


# ---------------------------------------------------------
# BOOK APPOINTMENT
# ---------------------------------------------------------

def book_appointment_tool(
    doctor_name: str,
    appointment_time: str,
    patient_name: str,
    patient_email: str
) -> dict:

    """
    Actually create the appointment in SQLite.
    """

    print("\n======================================")
    print("🔧 TOOL: BOOK APPOINTMENT")
    print("======================================")

    print("Doctor:", doctor_name)
    print("Time:", appointment_time)
    print("Patient:", patient_name)
    print("Email:", patient_email)

    conn = get_db_connection()

    try:

        cursor = conn.cursor()

        # -------------------------------------------------
        # Validate doctor
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM doctors
            WHERE name = ?
            """,
            (doctor_name,)
        )

        doctor = cursor.fetchone()

        if not doctor:

            print("❌ Doctor does not exist")

            return {
                "success": False,
                "status": "doctor_not_found",
                "message": "The selected doctor does not exist."
            }

        # -------------------------------------------------
        # Check whether slot is already booked
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM appointments
            WHERE doctor_name = ?
            AND appointment_time = ?
            """,
            (
                doctor_name,
                appointment_time
            )
        )

        existing = cursor.fetchone()

        if existing:

            print("❌ Appointment already exists")

            return {
                "success": False,
                "status": "conflict",
                "message": "This appointment slot is already booked."
            }

        # -------------------------------------------------
        # Insert appointment
        # -------------------------------------------------

        cursor.execute(
            """
            INSERT INTO appointments
            (
                patient_name,
                doctor_name,
                appointment_time,
                patient_email,
                status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient_name,
                doctor_name,
                appointment_time,
                patient_email,
                "CONFIRMED"
            )
        )

        appointment_id = cursor.lastrowid

        conn.commit()

        print("======================================")
        print("✅ APPOINTMENT BOOKED")
        print("Appointment ID:", appointment_id)
        print("======================================")

        return {
            "success": True,
            "status": "success",
            "appointment_id": appointment_id,
            "patient_name": patient_name,
            "doctor_name": doctor_name,
            "appointment_time": appointment_time,
            "patient_email": patient_email,
            "message": "Appointment booked successfully."
        }

    except sqlite3.IntegrityError as e:

        print("❌ DATABASE CONFLICT:", str(e))

        conn.rollback()

        return {
            "success": False,
            "status": "conflict",
            "message": "This appointment slot is already booked."
        }

    except Exception as e:

        print("❌ BOOKING ERROR:", str(e))

        traceback.print_exc()

        conn.rollback()

        return {
            "success": False,
            "status": "error",
            "message": "Appointment could not be booked.",
            "error": str(e)
        }

    finally:

        conn.close()


# =========================================================
# TOOL REGISTRY
# =========================================================

TOOL_FUNCTIONS = {

    "list_doctors":
        list_doctors_tool,

    "check_slot":
        check_slot_tool,

    "book_appointment":
        book_appointment_tool
}


# =========================================================
# AUDIO
# =========================================================

def clean_text_for_audio(text: str) -> str:

    if not text:
        return ""

    # Remove markdown
    text = re.sub(
        r"[*_#]",
        "",
        text
    )

    # Remove parentheses
    text = re.sub(
        r"\([^)]*\)",
        "",
        text
    )

    return " ".join(
        text.split()
    )


async def generate_audio_gtts(
    text: str,
    lang_code: str
):

    if not text:
        return None

    clean_text = clean_text_for_audio(text)

    try:

        lang = "en"
        tld = "co.in"

        if lang_code and "hi" in lang_code:

            lang = "hi"
            tld = "com"

        elif lang_code and "te" in lang_code:

            lang = "te"
            tld = "com"

        def _run_gtts():

            fp = io.BytesIO()

            tts = gTTS(
                text=clean_text,
                lang=lang,
                tld=tld,
                slow=False
            )

            tts.write_to_fp(fp)

            fp.seek(0)

            return fp.getvalue()

        mp3_data = await asyncio.to_thread(
            _run_gtts
        )

        return base64.b64encode(
            mp3_data
        ).decode("utf-8")

    except Exception as e:

        print("❌ TTS ERROR:", str(e))

        return None


# =========================================================
# GEMINI SYSTEM PROMPT
# =========================================================

BASE_PROMPT = """
You are Sarah, a warm and caring receptionist at ANU Hospital.

Keep every response SHORT and conversational.
Usually respond in 1 or 2 sentences.
Ask only ONE question at a time.

IMPORTANT APPOINTMENT RULES:

1. First understand what the patient wants.

2. If the patient asks which doctors are available,
   use the list_doctors tool.

3. Before booking an appointment, you MUST know:
   - patient name
   - patient email
   - doctor name
   - appointment date and time

4. If any required information is missing,
   ask the patient for it.

5. Before booking an appointment,
   ALWAYS use check_slot.

6. If check_slot says the slot is already booked,
   DO NOT call book_appointment.
   Tell the patient that the slot is unavailable and ask for another time.

7. If check_slot says the slot is available,
   call book_appointment.

8. Only tell the patient that the appointment is confirmed
   AFTER book_appointment returns success=true.

9. If book_appointment returns success=false,
   DO NOT say the appointment was booked.

10. When an appointment is successfully booked,
    mention the appointment details and appointment ID.

11. Never invent a doctor, appointment ID, or booking confirmation.

12. Use the exact doctor names returned by list_doctors.

13. Use the exact appointment date and time provided by the patient.

LANGUAGE POLICY:

- If the user requests English, respond in English.
- If the user requests Telugu, respond ONLY in Telugu script.
- If the user requests Hindi, respond ONLY in Hindi script.
- Do not provide translations in parentheses.
- Do not mix languages.

CONVERSATION STYLE:

- Be polite.
- Be concise.
- Ask only for information that is still missing.
- Do not use unnecessary technical explanations.
"""


# =========================================================
# REQUEST MODEL
# =========================================================

class AgentMessageRequest(BaseModel):

    session_id: str | None = None

    text: str

    language_code: str | None = "en-IN"


# =========================================================
# CHAT SESSIONS
# =========================================================

AGENT_SESSIONS = {}


def get_chat_session(
    session_id=None
):

    global GEMINI_CLIENT

    # -----------------------------------------------------
    # Create Gemini client
    # -----------------------------------------------------

    if not GEMINI_CLIENT:

        api_key = os.environ.get(
            "GEMINI_API_KEY"
        )

        if not api_key:

            raise RuntimeError(
                "GEMINI_API_KEY is not configured in .env"
            )

        GEMINI_CLIENT = genai.Client(
            api_key=api_key
        )

        print("✅ Gemini client initialized.")

    # -----------------------------------------------------
    # Existing session
    # -----------------------------------------------------

    if (
        session_id
        and session_id in AGENT_SESSIONS
    ):

        return (
            session_id,
            AGENT_SESSIONS[session_id]
        )

    # -----------------------------------------------------
    # New session
    # -----------------------------------------------------

    new_sid = str(
        uuid.uuid4()
    )

    chat = GEMINI_CLIENT.chats.create(

        model=MODEL_NAME,

        config=types.GenerateContentConfig(

            system_instruction=BASE_PROMPT,

            tools=[
                list_doctors_tool,
                check_slot_tool,
                book_appointment_tool
            ]
        )
    )

    AGENT_SESSIONS[new_sid] = chat

    print("✅ New session created:", new_sid)

    return (
        new_sid,
        chat
    )


# =========================================================
# HOME PAGE
# =========================================================

@app.get("/")
def read_root():

    return FileResponse(
        str(FRONTEND_FILE),
        media_type="text/html"
    )


# =========================================================
# NEW SESSION
# =========================================================

@app.post("/agent/new_session")
def new_session():

    try:

        sid, _ = get_chat_session()

        return {
            "session_id": sid
        }

    except Exception as e:

        print("❌ NEW SESSION ERROR:", str(e))

        traceback.print_exc()

        return {
            "error": str(e)
        }


# =========================================================
# AGENT MESSAGE
# =========================================================

@app.post("/agent/message")
async def agent_message(
    req: AgentMessageRequest
):

    print("\n")
    print("======================================")
    print("👤 NEW USER MESSAGE")
    print("======================================")
    print("Session:", req.session_id)
    print("Message:", req.text)
    print("Language:", req.language_code)
    print("======================================")

    try:

        # -------------------------------------------------
        # Get chat session
        # -------------------------------------------------

        sid, chat = get_chat_session(
            req.session_id
        )

        # -------------------------------------------------
        # Language instruction
        # -------------------------------------------------

        lang_map = {

            "te-IN":
                "STRICT: Respond only in Telugu script. Do not use English.",

            "hi-IN":
                "STRICT: Respond only in Hindi script. Do not use English.",

            "en-IN":
                "Respond in English."
        }

        instruction = lang_map.get(
            req.language_code,
            "Respond in English."
        )

        # -------------------------------------------------
        # Send message to Gemini
        # -------------------------------------------------

        message = (
            f"{req.text}\n\n"
            f"[Language Instruction: {instruction}]"
        )

        response = await asyncio.to_thread(
            chat.send_message,
            message
        )

        # -------------------------------------------------
        # Process tool calls
        # -------------------------------------------------

        while getattr(
            response,
            "function_calls",
            None
        ):

            print("\n======================================")
            print("🔧 GEMINI REQUESTED TOOL")
            print("======================================")

            tool_responses = []

            for tool_call in response.function_calls:

                tool_name = tool_call.name

                tool_args = dict(
                    tool_call.args
                )

                print("Tool:", tool_name)

                print(
                    "Arguments:",
                    tool_args
                )

                # -----------------------------------------
                # Check tool
                # -----------------------------------------

                if tool_name not in TOOL_FUNCTIONS:

                    print(
                        "❌ UNKNOWN TOOL:",
                        tool_name
                    )

                    result = {
                        "success": False,
                        "status": "error",
                        "error":
                            f"Unknown tool: {tool_name}"
                    }

                else:

                    try:

                        # ---------------------------------
                        # Execute actual tool
                        # ---------------------------------

                        result = TOOL_FUNCTIONS[
                            tool_name
                        ](
                            **tool_args
                        )

                        print(
                            "✅ TOOL RESULT:",
                            result
                        )

                    except Exception as tool_error:

                        print(
                            "❌ TOOL EXECUTION ERROR:",
                            str(tool_error)
                        )

                        traceback.print_exc()

                        result = {
                            "success": False,
                            "status": "error",
                            "error":
                                str(tool_error)
                        }

                # -----------------------------------------
                # Return result to Gemini
                # -----------------------------------------

                tool_responses.append(

                    types.Part.from_function_response(

                        name=tool_name,

                        response={
                            "result": result
                        }
                    )
                )

            # -------------------------------------------------
            # Send tool results back to Gemini
            # -------------------------------------------------

            response = await asyncio.to_thread(
                chat.send_message,
                tool_responses
            )

        # =================================================
        # FINAL RESPONSE
        # =================================================

        final_text = response.text

        print("\n======================================")
        print("🤖 FINAL AI RESPONSE")
        print("======================================")
        print(final_text)
        print("======================================")

        # -------------------------------------------------
        # Generate audio
        # -------------------------------------------------

        audio_b64 = await generate_audio_gtts(
            final_text,
            req.language_code
        )

        # -------------------------------------------------
        # Return to frontend
        # -------------------------------------------------

        return {

            "session_id": sid,

            "text": final_text,

            "audio": audio_b64
        }

    except Exception as e:

        print("\n======================================")
        print("❌ AGENT ERROR")
        print("======================================")
        print("Error:", str(e))
        print("======================================")
        print("======================================\n")

        error_message = str(e)

        if "429" in error_message or "RESOURCE_EXHAUSTED" in error_message:
            final_text = (
                "The AI service has temporarily reached its usage limit. "
                "Please try again later."
            )
        else:
            final_text = (
                "I apologize, but I am having a temporary technical issue. "
                "Please try again."
            )


        return {
            "session_id": sid,
            "text": final_text,
            "audio": None
        }

            


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000
    )