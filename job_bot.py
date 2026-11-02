import os
import asyncio
import json
from jobspy import scrape_jobs
from google import genai
from google.genai import types
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, ContextTypes

# Load environment variables
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

class CloudJobAutomation:
    def __init__(self):
        self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        self.approval_status = None
        self.telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        self.telegram_app.add_handler(CallbackQueryHandler(self._button_callback))

    async def _button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if query.data == "approve":
            self.approval_status = True
            await query.edit_message_text(text="✅ **Approved from mobile!** Job marked for application.")
        else:
            self.approval_status = False
            await query.edit_message_text(text="❌ **Skipped.** Moving to next listing.")

    async def send_approval_card(self, job, score, pitch):
        self.approval_status = None
        keyboard = [[
            InlineKeyboardButton("✅ Approve & Submit", callback_data="approve"),
            InlineKeyboardButton("❌ Skip Job", callback_data="reject")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message_text = (
            f"🚨 **New High-Match Job Found!**\n\n"
            f"💼 **Role:** {job['title']}\n"
            f"🏢 **Company:** {job['company']}\n"
            f"📍 **Location:** {job['location']}\n"
            f"⭐ **Gemini Match Score:** {score}/100\n\n"
            f"📝 **Tailored Pitch:**\n{pitch}\n\n"
            f"🔗 [View Job Listing]({job['job_url']})"
        )

        await self.telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message_text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

        # Poll for mobile tap up to 3 minutes
        await self.telegram_app.initialize()
        await self.telegram_app.start()
        await self.telegram_app.updater.start_polling(drop_pending_updates=True)

        start_time = asyncio.get_event_loop().time()
        while self.approval_status is None:
            if (asyncio.get_event_loop().time() - start_time) > 180:
                self.approval_status = False
                break
            await asyncio.sleep(1)

        await self.telegram_app.updater.stop()
        await self.telegram_app.stop()
        await self.telegram_app.shutdown()
        return self.approval_status

    def run_pipeline(self):
        with open("my_resume.md", "r") as f:
            resume_text = f.read()

        print("🔍 Scraping recent job listings...")
        jobs = scrape_jobs(
            site_name=["linkedin", "indeed"],
            search_term="Software Engineer",
            location="Bengaluru, Karnataka, India",
            results_wanted=5,
            hours_old=24
        )

        if jobs.empty:
            print("No new jobs found.")
            return

        for _, job in jobs.iterrows():
            prompt = f"""
            Compare my resume with this job description.
            Return ONLY valid JSON with:
            - "match_score": integer (0-100)
            - "should_apply": boolean (true if score >= 75)
            - "tailored_pitch": a 3-sentence professional cover pitch for this role

            RESUME:
            {resume_text}

            JOB ({job['title']} at {job['company']}):
            {job['description']}
            """

            try:
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
                )
                result = json.loads(response.text)

                if result.get("should_apply") and result.get("match_score", 0) >= 75:
                    print(f"✨ Match found: {job['title']} at {job['company']} ({result['match_score']}%)")
                    approved = asyncio.run(self.send_approval_card(job, result['match_score'], result['tailored_pitch']))
                    if approved:
                        print(f"🚀 User approved {job['company']} from mobile!")
                    else:
                        print(f"🛑 User skipped or timed out on {job['company']}.")
                else:
                    print(f"Skipping {job['title']} at {job['company']} (Score below threshold).")
            except Exception as e:
                print(f"Error evaluating job: {e}")

if __name__ == "__main__":
    bot = CloudJobAutomation()
    bot.run_pipeline()