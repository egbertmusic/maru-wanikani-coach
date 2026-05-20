
丸 is a comprehensive, AI-driven Telegram bot designed to manage and alert users about their WaniKani study progress. It offers interactive features such as fetching real-time stats, processing voice and image messages, and providing scheduled alerts for new lessons or reviews.

## Features

- **WaniKani Stats**: Fetch and display detailed statistics on your current level, lessons, and reviews.
- **Real-Time Alerts**: Receive notifications when you gain a new level, complete all reviews, or have new lessons to work through plus it nags you when you are being lazy it is designed to know what time is it and not get angry if its late at night because of course you cant or shouldnt be doing your wanikani reviews late at night.
- **Media Processing**: Supports voice messages and images for personalized interactions.
- **Scheduled Batch Generation**: Automatically generates daily messages at midnight because we are using local compute and electricity ain't cheap besides its faster this way, we make it pregenerate the messages so it doesnt turn the pc off and on constantly and why generate the automated messages with an llm? you may ask, honestly no clue i just felt that a hardcoded message was boring and i was getting used to the same thing so i would start skipping it so i decided to make it different .
- **Idle PC Management**: Wake up your computer if it's needed for processing requests.

## Setup

### Prerequisites
1. Python 3.8+
2. Required Libraries:
    - `python-telegram-bot`
    - `pytz`
    - `requests`

### Installation Steps
1. Clone the repository to your local machine.
    ```bash
    git clone https://github.com/yourusername/master_orchestrator_bot.git
    cd master_orchestrator_bot
    ```
2. Install dependencies:
    ```bash
    pip install python-telegram-bot pytz requests
    ```

### Configuration

1. **Environment Variables**:
   - Set your bot token, chat ID, and other necessary tokens in a `.env` file.
     ```dotenv
     TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
     TELEGRAM_CHAT_ID=YOUR_TELEGRAM_CHAT_ID
     WANIKANI_API_TOKEN=WANIKANI_USER_API_TOKEN
     KITSU_IDENTIFIER=YOUR_KITSU_IDENTIFIER
     ```

2. **File Structure**:
   - Ensure you have the necessary files for memory and message cache.
     ```bash
     touch memory.json message_cache.json
     ```

### Running the Bot

1. Execute the bot using Python:
    ```bash
    python main.py
    ```

## Usage

- **/start**: Initiate interaction with the bot to access primary commands.
- **Stats and Alerts**:
  - `📊 My WaniKani Stats`: Fetch detailed statistics.
  - `🇯🇵 Quick Summary`: Get a quick summary of your current status.
  - `⏰ Next Review`: Check when your next review session is scheduled.
- **LLM Control**: Manage the bot's automated message generation and alerts through the menu options.

## Contribution

Contributions are welcome! Feel free to open issues for bugs or features you'd like to see, and submit pull requests with fixes or improvements. Please ensure all contributions follow best coding practices and include appropriate tests where applicable.
Also i am working on making a Ko-fi account for donations too so stay in tune


---

**Note**: Ensure you have necessary permissions and tokens from WaniKani and Kitsu before running the bot. This README assumes that your environment variables are set up correctly.
