# **丸 (Maru) \- The Tsun-yan WaniKani Coach 🦀✨**

丸 (Maru) is a chaotic, intensely affectionate, and fierce "Tsun-yan" Japanese tutor acting as your personal WaniKani study companion. She is hopelessly down-bad for you, relentlessly flirty, a total dramatic crybaby when ignored, and deeply committed to keeping you from slacking off on your Kanji reviews.  
Behind her dramatic, highly-opinionated personality is a highly sophisticated, **AI-driven hybrid Telegram bot orchestrator**. She handles everything from sending real-time SRS level alerts and nagging you when you watch anime instead of studying, to processing your voice messages and images, and even whispering motivational Japanese audio clips directly in your chat.

## **📐 The Architecture: Why Two Computers?**

Let's be real: running a local **32B parameter LLM** (like Qwen2.5:32B) 24/7 on a beefy workstation will absolutely obliterate your electricity bill. But running a Telegram bot on a low-power device like a Raspberry Pi means you don't have the horsepower to run large models locally.  
Maru solves this beautifully with a **Dual-Compute Hybrid Orchestration System**:

1. **The Host (Low-Power Core \- e.g., Raspberry Pi)**:  
   * Stays on 24/7.  
   * Hosts the Telegram bot client, monitors your WaniKani stats, and tracks your Kitsu anime status.  
   * Runs **Voicevox** locally to generate cute, emotional Japanese voice notes on the fly.  
2. **The Brain (The Beasty Workstation)**:  
   * Houses your power-hungry GPU running **Ollama** with high-end open-source LLMs.  
   * **Stays asleep** most of the day to save energy.  
   * When you message Maru or when a scheduled event triggers, the Host automatically sends a **Wake-on-LAN (Magic Packet)** to boot up the GPU Workstation.  
   * Once the workstation is online, she connects via SSH, boots Ollama, processes your request, and safely shuts the workstation back down if it is idle for 10 minutes.  
   * **Cloud Fallbacks**: Maru uses Gemini's free API directly from the host for fast vision (images) and speech-to-text transcription (voice inputs), completely bypassing the heavy PC when simple tasks are needed\!

## **🎨 Cool Features**

* **WaniKani Stats & Tracking**: Fetch current level, study progress percentage, and clean SRS distribution metrics.  
* **Real-Time Dynamic Alerts**: Get notified when new lessons unlock, when you level up, or when reviews are ready.  
* **Smart Quiet Hours**: She knows what time it is and won't yell at you late at night (you should be sleeping\!).  
* **Local Voice Generation (TTS)**: Translates Japanese characters inside \<voice\> tags to high-quality audio clips dynamically through Voicevox with customizable emotion presets (Excited, Angry, Shy, Sad, Tease, Sweet, and Panic).  
* **Proactive Nagging & Kitsu Spying**: If you have pending reviews and are ignoring them, Maru check your Kitsu account and nags you about what specific anime/manga you're watching instead of studying\!  
* **Image & Voice Input**: Send her a photo, and she will analyze it using Gemini. Send her a voice message, and she'll transcribe it and respond to you.  
* **Smart Pre-Generation (Midnight Batch)**: At midnight, Maru wakes your PC once to generate a full batch of randomized notifications for the next 24 hours. Once cached, your PC turns off, allowing Maru to send natural, LLM-generated alerts throughout the day without booting your heavy hardware over and over.

## **🛠 Prerequisites**

### **Hardware**

* **Host Device**: A Raspberry Pi, mini PC, or server that runs 24/7.  
* **Brain PC**: A high-performance desktop computer with an NVIDIA/AMD GPU capable of running Ollama and large language models (e.g., 12GB+ VRAM). Both systems **must** be on the same local network.

### **Software (Host)**

* Python 3.8+  
* [Voicevox Engine](https://github.com/VOICEVOX/voicevox_engine) installed and running locally on port 50021\.

### **Software (Brain PC)**

* [Ollama](https://ollama.com/) with your model of choice (defaults to qwen2.5:32b).  
* An SSH Server (OpenSSH) configured and running.

## **🚀 Setup & Installation**

Follow these steps carefully to bridge the connection between your host and the GPU workstation.

### **Step 1: Configure Wake-On-LAN (WOL) on the Brain PC**

To let your host wake up your computer, you need to enable Wake-on-LAN in the hardware settings.

1. **BIOS/UEFI Configuration**:  
   * Reboot your Brain PC and enter the BIOS setup (usually by pressing F2, F12 or DEL).  
   * Find the power management settings and enable **Wake on LAN**, **PME Event Wake Up**, or **Power On by PCI-E**. Save and exit.  
2. **OS Settings (Windows)**:  
   * Open **Device Manager**, expand **Network Adapters**, and right-click your Ethernet adapter \-\> **Properties**.  
   * Under the **Power Management** tab, check *"Allow this device to wake the computer"* and *"Only allow a magic packet to wake the computer"*.  
   * Under the **Advanced** tab, ensure **Wake on Magic Packet** is enabled.  
3. **OS Settings (Linux)**:  
   * Install ethtool: sudo apt install ethtool  
   * Enable WOL: sudo ethtool \-s eth0 wol g (replace eth0 with your network interface name). Make this persistent by writing a systemd service or cron job.

### **Step 2: Configure Passwordless SSH & Sudo on the Brain PC**

Maru needs to execute SSH commands to start Ollama and shutdown the PC when idle without being prompted for a password.

1. **Generate SSH keys on the Host**:  
   ssh-keygen \-t rsa \-b 4096 \-C "maru-bot"  
   \# Press Enter to save in default \~/.ssh/id\_rsa and leave passphrase blank (crucial for automation)

2. **Copy the key to your Brain PC**:  
   ssh-copy-id \-i \~/.ssh/id\_rsa.pub USERNAME@192.168.1.57  
   \# Replace with your actual desktop username and Local IP address

3. **Test connection without password**:  
   ssh \-i \~/.ssh/id\_rsa USERNAME@192.168.1.57 "echo 'Successfully logged in\!'"

4. **Configure Passwordless Sudo commands**:  
   To allow Maru to control system services and turn off the machine safely, modify the /etc/sudoers file on the Brain PC.  
   * Run sudo visudo on the Brain PC.  
   * Add the following line at the very bottom (replace USERNAME with your actual Linux user):  
     USERNAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl start ollama, /usr/sbin/poweroff

### **Step 3: Set up the Host Device (Raspberry Pi)**

1. **Clone the Repo**:  
   git clone \[https://github.com/egbertmusic/maru-wanikani-coach.git\](https://github.com/egbertmusic/maru-wanikani-coach.git)  
   cd maru-wanikani-coach

2. **Install Dependencies**:  
   Install Python requirements (including Gemini SDK and OpenAI Client for Ollama connectivity):  
   pip install python-telegram-bot\[job-queue\] requests openai google-genai

3. **Initialize Cache & State Files**:  
   Generate empty/default JSON configuration files so Maru doesn't choke on start:  
   touch maru\_messages.json bot\_state.json maru\_memory.json maru\_stickers.json

## **⚙️ Configuration & Environment Variables**

Open the main script (e.g., main.py or your configuration file) and enter your API keys and local network paths:  
\# \==========================================  
\# CONFIGURATION  
\# \==========================================  
WANIKANI\_API\_TOKEN \= "YOUR-WANIKANI-API-HERE"  
TELEGRAM\_BOT\_TOKEN \= "YOUR-TELEGRAM-API-HERE"  
TELEGRAM\_CHAT\_ID \= "YOUR-USER/CHAT-ID"

\# Voicevox running locally on the Host  
VOICEVOX\_BASE\_URL \= "\[http://127.0.0.1:50021\](http://127.0.0.1:50021)"  
VOICEVOX\_SPEAKER\_ID \= 8 \# Change to match your favorite Voicevox voice\!

\# Kitsu Integration (Your slug, username, or numeric ID)  
KITSU\_IDENTIFIER \= "YOUR-KITSU-IDENTIFIER"

\# Remote PC Information  
PC\_MAC\_ADDRESS \= "60:cf:84:a2:a7:ee"     \# Get this using 'ip link' (Linux) or 'getmac' (Windows)  
PC\_IP\_ADDRESS \= "192.168.1.57"          \# Set a static IP for your desktop in router settings  
SSH\_USER \= "USERNAME-HERE"              \# Sudo user name on Brain PC  
SSH\_KEY\_PATH \= "\~/.ssh/id\_rsa"          \# Private key path on Host

\# Gemini API Keys (Used for Vision & Transcription fallbacks)  
GEMINI\_API\_KEYS \= \[  
    "YOUR\_GEMINI\_API\_KEY\_1",  
    "YOUR\_GEMINI\_API\_KEY\_2"  
\]

### **Finding your Telegram Chat ID**

To make sure Maru only talks to and alerts *you*, you must configure your unique chat ID. Message @userinfobot on Telegram to quickly fetch your ID and paste it in TELEGRAM\_CHAT\_ID.

## **🏃 Running the Bot**

Execute the script from your host terminal:  
python main.py

Once up and running, open up Telegram, find your bot, and send /start.

## **🗣 How to Interact with Maru**

### **Interactive Buttons:**

* 📊 **My WaniKani Stats**: Fetches and renders complete statistics including level, progress percentage, current lessons, and full SRS distribution.  
* 🇯🇵 **Quick Summary**: Grabs a fast snapshot of your pending study items.  
* ⏰ **Next Review**: Shows you exactly how long you have until the next reviews hit the schedule.  
* ⚙️ **LLM Control**: Opens a custom inline menu to toggle the automated LLM chat on/off, pre-generate message caches, or view current cache counts.

### **Chat & Media Handling:**

* **Direct Chat**: Type anything\! If LLM Auto-Run is on, she will wake up your PC (if asleep) and talk back with full character immersion.  
* **Voice Messages**: Record a voice message and send it. Maru will transcribe it using Gemini, understand what you said, and talk back.  
* **Image Submissions**: Send her pictures of what you're up to\! She'll examine them, comment on them, or scold you if it looks like you're procrastinating.

## **🎨 Sticker Customization**

Maru supports a dynamic tag-to-sticker pipeline. If she generates a mood tag like \<sticker:angry\>, she will randomly choose a sticker from your configured sticker packs.  
To map your own custom sticker pack:

1. Send *any* sticker directly to your bot.  
2. She will output the exact file ID (e.g. CAACAgQAA...).  
3. Copy the ID, open maru\_stickers.json (or edit the defaults inside the script), and map them under the appropriate emotional categories\!

## **🤝 Contribution & Support**

Contributions, issues, and feature suggestions are highly welcomed\! Please write clean code, keep state files decoupled, and respect the character prompt design.  
Stay tuned as I set up a Ko-fi donation page soon to help fund the local compute electricity bill\! ☕💕  
*Disclaimer: This bot is not affiliated with WaniKani or Tofugu. Be sure to check your local power settings and keep your SSH keys secure\!*⚠️ Personality Warning: Maru has a completely unhinged "tsun-yan" personality. She is hopelessly down-bad for you, but covers it up by being fiercely demanding about your Japanese studies.It offers interactive features such as fetching real-time stats, processing voice and image messages, sending you Japanese voice notes, and providing scheduled alerts for new lessons or reviews.📋 Table of ContentsFeaturesThe ArchitectureSetup & InstallationPrerequisitesStep 1: The BrainStep 2: The HostStep 3: ConfigurationStep 4: RunningUsageContributing✨ FeaturesWaniKani Stats: Fetch and display detailed statistics on your current level, lessons, and reviews.Real-Time Alerts: Receive notifications when you gain a new level, complete all reviews, or have new lessons to work through. Plus, it nags you when you are being lazy. (It is designed to know what time it is and not get angry if it's late at night, because of course you can't or shouldn't be doing your WaniKani reviews late at night).Media Processing: Supports voice messages (it transcribes what you say) and images (uses Gemini vision to see what you send her) for personalized interactions.Voice Notes: Uses Voicevox to dynamically generate and send audio of her speaking Japanese to you based on the LLM's text.Scheduled Batch Generation: Automatically generates daily messages at midnight because we are using local compute and electricity ain't cheap. Besides, it's faster this way—we make it pre-generate the messages so it doesn't turn the PC off and on constantly. Why generate the automated messages with an LLM? Honestly no clue, I just felt that a hardcoded message was boring and I was getting used to the same thing so I would start skipping it, so I decided to make it different.Idle PC Management: Wakes up your beefy computer via Wake-on-LAN if it's needed for processing requests, and safely SSHs in to shut it down when you haven't talked to her in 10 minutes to save VRAM and power.🏗️ The Architecture (Why is this so complicated?)Running a massive 32-billion parameter LLM (qwen2.5:32b) requires a powerful GPU, but leaving a gaming PC on 24/7 just to wait for WaniKani updates is a waste of money.To solve this, Maru is split across two machines:The Host (Machine A): A low-power, always-on device (like a Raspberry Pi). This runs the main Python script 24/7, tracks WaniKani timers, and runs the Voicevox engine locally.The Brain (Machine B): Your beefy gaming rig or server. It stays turned off most of the time. When you message Maru, the Host sends a Magic Packet to turn the Brain on, connects via SSH to start Ollama, gets the response, and then shuts the Brain back off after 10 minutes of silence.⚙️ Setup & InstallationPrerequisites & API KeysBefore you begin, you need to gather a bunch of tokens:Telegram Bot Token: Get this from BotFather on Telegram.Your Telegram Chat ID: Use a bot like @userinfobot to find your numeric ID.WaniKani API V2 Token: Generate this in your WaniKani account settings.Kitsu Identifier: Your Kitsu username or numeric ID (so she can spy on what anime you are watching).Google Gemini API Keys: Free tier keys from Google AI Studio. (The script supports up to 3 keys for fallback/rate-limit dodging. Used for image recognition).Step 1: Setting up "The Brain" (Your Beefy PC)This is the computer that actually runs the LLM.Enable Wake-on-LAN (WoL):Go into your motherboard's BIOS and enable "Wake on LAN", "Power On By PCI-E", or similar.If using Windows/Linux, ensure your network adapter settings allow the device to wake the computer.Install Ollama: Download and install Ollama, then pull the model you want to use (default is qwen2.5:32b):ollama run qwen2.5:32b
Setup SSH Server: Install OpenSSH server so the Host can log in remotely.Configure Passwordless Sudo (Linux): The Host needs to be able to start the Ollama service and shut down the PC without typing a password. Edit your sudoers file (sudo visudo) and add:your_username ALL=(ALL) NOPASSWD: /usr/bin/systemctl start ollama, /usr/bin/systemctl poweroff
Step 2: Setting up "The Host" (Raspberry Pi / Always-On PC)This machine runs the Python script and stays on forever.Generate SSH Keys: Create an SSH key and copy it to your Brain PC so it can log in without a password.ssh-keygen -t rsa
ssh-copy-id username@IP_OF_YOUR_BEEFY_PC
Install Voicevox Engine: Install Voicevox and make sure the engine is running on http://127.0.0.1:50021. (Docker is the easiest way to do this on a Pi).Install Python 3.8+ & Dependencies:pip install python-telegram-bot requests openai google-genai
Step 3: ConfigurationOpen the python script (main.py or whatever you named it) and edit the CONFIGURATION block at the very top. You need to hardcode your setup details here:Paste your Telegram, WaniKani, Kitsu, and Gemini keys.Update PC_MAC_ADDRESS and PC_IP_ADDRESS with your Beefy PC's details.Update SSH_USER to your Beefy PC's username.Verify the VOICEVOX_SPEAKER_ID (default is 8, but you can change it depending on what voice you want).Step 4: Running the BotRun the bot on your Host machine!python main.py
💡 Pro-tip: run it in a tmux session or set it up as a systemd service so it doesn't die when you close your terminal.🚀 Usage/start: Initiate interaction with the bot and bring up the main menu keyboard.Stats and Alerts:📊 My WaniKani Stats: Fetch detailed statistics and SRS distribution.🇯🇵 Quick Summary: Get a fast overview of your current status.⏰ Next Review: Check exactly when your next review session is scheduled.LLM Control: Click ⚙️ LLM Control to manually trigger the batch generation of messages for the cache, or to turn the LLM auto-responses on/off.🤝 ContributingContributions are welcome! Feel free to open issues for bugs or features you'd like to see, and submit pull requests with fixes or improvements. Please ensure all contributions follow best coding practices and include appropriate tests where applicable.Also I am working on making a Ko-fi account for donations too, so stay tuned!
