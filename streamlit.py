import streamlit as st
import json
import _snowflake
import requests as re

from snowflake.snowpark.context import get_active_session

API_ENDPOINT = "/api/v2/cortex/inference:complete"
API_TIMEOUT = 50000  # in milliseconds

session = get_active_session()

messages = []

def get_weather(location):
    try:
        apiKey = '<Your Weatherapi.com API KEY>';
        url = f'https://api.weatherapi.com/v1/current.json?key={apiKey}&q={location}';

        headers = {
            "Content-Type": "application/json"
        }
        response = re.get(url, headers=headers);
        weatherData = response.json();
        response.raise_for_status()
        current_weather = weatherData.get('current')
        condition = current_weather.get('condition')
        text = condition.get('text')
        icon = condition.get('icon')
        return text, icon
        
    except re.exceptions.HTTPError as err:
        st.error(f"HTTP error occurred: {err}")
    except Exception as e:
        st.error(f"Error to get weather: {e}")
    return "We were not able to get the weather.", ""

def call_snowflake_claude():
    """
    Make an API call to Snowflake's Claude integration.
    
    Args:
        user_message (str): The message to send to Claude
        location (str): The location to get weather for
    
    Returns:
        The response from the API
    """
    text = ""
    tool_name = None
    tool_use_id = None
    tool_input = ""
    tool_input_json = None
    
    payload = {
        "model": "claude-3-5-sonnet",
        "messages": messages,
        "tool_choice": {
            "type": "auto",
            "name": [
                "get_weather"
            ]
        },
        "tools": [
            {
                "tool_spec": {
                    "type": "generic",
                    "name": "get_weather",
                    "description": "Given a location return the weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state, e.g. in San Francisco, CA"
                            }
                        },
                        "required": [
                            "location"
                        ]
                    }
                }
            }
        ]
    }

    try:
        resp = _snowflake.send_snow_api_request(
            "POST",  # method
            API_ENDPOINT,  # path
            {},  # headers
            {},  # params
            payload,  # body
            None,  # request_guid
            API_TIMEOUT,  # timeout in milliseconds,
        )
        try:
            response_content = json.loads(resp["content"])
            # st.write(response_content)
            for response in response_content:
                data = response.get('data', {})
                for choice in data.get('choices', []):
                    delta = choice.get('delta', {})
                    content_list = delta.get('content_list', [])
                    for content in content_list:
                        content_type = content.get('type')
                        if content_type == 'text':
                            text += content.get('text', '')
                        if content_type is None:
                            if content.get('tool_use_id'):
                                tool_name = content.get('name')
                                tool_use_id = content.get('tool_use_id')
                            tool_input += content.get('input', '')
            if tool_input != '':
                try:
                    tool_input_json =  json.loads(tool_input)
                except json.JSONDecodeError:
                    st.error("Issue with Tool Input")
                    st.error(tool_input)
        except json.JSONDecodeError:
            st.error("❌ Failed to parse API response. The server may have returned an invalid JSON format.")

            if resp["status"] != 200:
                st.error(f"Error:{resp} ")
            return None
            
        return text, tool_use_id, tool_name, tool_input_json
            
    except Exception as e:
        st.error(f"Error making request: {str(e)}")
        return None

def main():
    st.title("Weather Tool Use")

    st.session_state.messages = []

    # Initialize session state
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message['role']):
            st.markdown(message['content'])

    if query := st.chat_input("Would you like to learn?"):
        # Add user message to chat
        with st.chat_message("user"):
            st.markdown(query)
        st.session_state.messages.append({"role": "user", "content": query})
        messages.append({"role": "user", "content": query})
        
        # Get response from API
        with st.spinner("Processing your request..."):
            text, tool_use_id, tool_name, tool_input_json = call_snowflake_claude()
 
        with st.chat_message("assistant"):
            st.markdown(text)
            st.session_state.messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role":"assistant",
                     "content":text,
                     "content_list": [
                         {
                             "type": "tool_use",
                             "tool_use": {
                                 "tool_use_id": tool_use_id,
                                 "name": tool_name,
                                 "input": tool_input_json
                             }
                         }
                     ]
                }
            )

        if tool_name == 'get_weather':
            with st.spinner(f'Utilizing {tool_name} Tool..'):
                location = tool_input_json.get('location')
                if location:
                    weather, icon = get_weather(location)
                    messages.append(
                        {
                            'role': 'user',
                            'content' : query,
                            'content_list': [
                                {
                                    'type': 'tool_results',
                                    'tool_results' : {
                                        'tool_use_id' : tool_use_id,
                                        'name': tool_name,
                                        'content' : [
                                            {
                                                'type': 'text',
                                                'text': weather
                                            }
                                        ]
                                    } 
                                }
                            ]
                        }
                    )
                    text, tool_use_id, tool_name, tool_input_json = call_snowflake_claude()
                    with st.chat_message("assistant"):
                        st.markdown(text)
                        st.image(icon.replace('//','https://'))
                        st.session_state.messages.append({"role": "assistant", "content": text})

if __name__ == "__main__":
    main()