import re
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from openai import OpenAI
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["15 per minute"],
    storage_uri="memory://",
)

CORS(app)

# Init client
api_key = "API Key Here"
assistant_id = "Assistant ID Here"

client = OpenAI(api_key=api_key)
assistant = client.beta.assistants.retrieve(assistant_id)

ongoing_chats = {}


# Cleanup all chats over an hour old
def cleanup_old_chats():
    # Get chats over an hour old
    keys_to_remove = []
    for key in ongoing_chats.keys():
        current_time = datetime.now()
        last_interaction = ongoing_chats[key]["LastInteraction"]
        difference = current_time - last_interaction
        difference_in_minutes = difference.total_seconds() / 60

        if difference_in_minutes >= 60:
            keys_to_remove.append(key)

    # Delete chats over an hour old
    for key in keys_to_remove:
        current_item = ongoing_chats.pop(key)
        client.beta.threads.delete(current_item["ThreadId"])

@app.route("/", methods=["GET"])
def home():
    return render_template("chat.html")

# Generate response
@app.route("/api/chat/<reference>", methods=["POST"])
@limiter.limit("20 per minute")
def chat(reference):
    # Cleanup old chats
    cleanup_old_chats()

    user_input = request.json["Input"]

    # If no reference for current chat, create a new thread
    if reference not in ongoing_chats.keys():
        thread = client.beta.threads.create()

        # Add to our store of chats
        ongoing_chats[reference] = {
            "ThreadId": thread.id,
            "LastInteraction": datetime.now()
        }

    # Otherwise update last interaction and get current thread
    else:
        current = ongoing_chats[reference]
        current["LastInteraction"] = datetime.now()

        thread = client.beta.threads.retrieve(current["ThreadId"])

    # Now create a new message in the thread
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=user_input
    )

    # Run the updated thread against the assistant
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id
    )

    # Wait for the run to finish processing
    wait_on_run(run, thread)

    # Get the updated thread messages
    messages = client.beta.threads.messages.list(thread_id=thread.id)

    # Get the response to display
    response = messages.data[0].content[0].text.value

    # Prettify response
    response = prettify_response(response)

    return jsonify({"Response": response})


def prettify_response(response):
    response = response.replace("##", "")
    response = response.replace("*", "")
    response = response.replace("-", "")
    response = response.replace("\n", "<br>")
    response = re.sub('【.*?†source】', '', response)  # Remove citations
    return response


def wait_on_run(run, thread):
    while run.status == "queued" or run.status == "in_progress":
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id,
        )
        time.sleep(0.5)
    return run


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
