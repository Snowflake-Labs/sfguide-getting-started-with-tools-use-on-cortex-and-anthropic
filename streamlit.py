import streamlit as st
import json
import _snowflake
import requests as re

from snowflake.snowpark.context import get_active_session

API_ENDPOINT = "/api/v2/cortex/inference:complete"
API_TIMEOUT = 50000  # in milliseconds

session = get_active_session()

def get_weather(location):
    try:
        apiKey = '<YOUR WEATHERAPI API KEY>'
        url = f'https://api.weatherapi.com/v1/current.json?key={apiKey}&q={location}'

        headers = {
            "Content-Type": "application/json"
        }
        response = re.get(url, headers=headers)
        response.raise_for_status()  # Check for HTTP errors first
        weatherData = response.json()
        
        current_weather = weatherData.get('current')
        if not current_weather:
            return "Weather data not available.", ""
            
        condition = current_weather.get('condition', {})
        text = condition.get('text', 'Weather condition unknown')
        icon = condition.get('icon', '')
        
        # Add more weather details
        temp_f = current_weather.get('temp_f', 'N/A')
        humidity = current_weather.get('humidity', 'N/A')
        wind_mph = current_weather.get('wind_mph', 'N/A')
        
        detailed_weather = f"{text}. Temperature: {temp_f}°F, Humidity: {humidity}%, Wind: {wind_mph} mph"
        return detailed_weather, icon
        
    except re.exceptions.HTTPError as err:
        st.error(f"HTTP error occurred: {err}")
        return "Unable to fetch weather data due to HTTP error.", ""
    except Exception as e:
        st.error(f"Error getting weather: {e}")
        return "Unable to fetch weather data.", ""

def call_snowflake_claude(messages_list):
    """
    Make an API call to Snowflake's Claude integration.
    
    Args:
        messages_list (list): The conversation messages
    
    Returns:
        tuple: (text, tool_use_id, tool_name, tool_input_json)
    """
    text = ""
    tool_name = None
    tool_use_id = None
    tool_input = ""
    tool_input_json = None
    
    payload = {
        "model": "claude-3-7-sonnet",
        "messages": messages_list,
        "tools": [
            {
                "tool_spec": {
                    "type": "generic",
                    "name": "get_weather",
                    "description": "Get current weather information for a specified location",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state or city and country (e.g., San Francisco, CA or London, UK)"
                            }
                        },
                        "required": ["location"]
                    }
                }
            }
        ]
    }

    try:
        resp = _snowflake.send_snow_api_request(
            "POST",
            API_ENDPOINT,
            {},
            {},
            payload,
            None,
            API_TIMEOUT,
        )

        if resp["status"] != 200:
            st.error(f"API Error: {resp}")
            return None, None, None, None

        try:
            response_content = json.loads(resp["content"])
            
            for response in response_content:
                data = response.get('data', {})
                for choice in data.get('choices', []):
                    delta = choice.get('delta', {})
                    content_list = delta.get('content_list', [])
                    
                    for content in content_list:
                        content_type = content.get('type')
                        
                        if content_type == 'text':
                            text += content.get('text', '')
                        elif content_type is None:
                            # Handle tool use based on your original pattern
                            if content.get('tool_use_id'):
                                tool_name = content.get('name')
                                tool_use_id = content.get('tool_use_id')
                            tool_input += content.get('input', '')
                            
            if tool_input != '':
                try:
                    tool_input_json = json.loads(tool_input)
                except json.JSONDecodeError:
                    st.error("Issue with Tool Input")
                    st.error(tool_input)
                    tool_input_json = None
                                    
        except json.JSONDecodeError as e:
            st.error(f"Failed to parse API response: {e}")
            return None, None, None, None
            
        return text, tool_use_id, tool_name, tool_input_json
            
    except Exception as e:
        st.error(f"Error making API request: {str(e)}")
        return None, None, None, None

def main():
    st.title("Weather Tool Use")

    # Initialize session state properly
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    
    # Initialize conversation messages for API
    if 'conversation_messages' not in st.session_state:
        st.session_state.conversation_messages = []

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
            # Show weather icon if it exists
            if 'icon' in message:
                st.image(message['icon'])

    if query := st.chat_input("Ask me about the weather!"):
        # Add user message to chat
        with st.chat_message("user"):
            st.markdown(query)
        st.session_state.messages.append({"role": "user", "content": query})
        
        # Add to conversation messages for API (ensure content is never empty)
        user_message = {"role": "user", "content": query}
        st.session_state.conversation_messages.append(user_message)
        
        # Get initial response from Claude
        with st.spinner("Processing your request..."):
            text, tool_use_id, tool_name, tool_input_json = call_snowflake_claude(st.session_state.conversation_messages)
        
        if text is None:
            st.error("Failed to get response from Claude")
            return
            
        # Display Claude's initial response
        with st.chat_message("assistant"):
            st.markdown(text)
        
        # Add assistant response to conversation (ensure content is never empty)
        assistant_message = {
            "role": "assistant",
            "content": text if text else "Processing your weather request..."
        }
        
        # If Claude wants to use the weather tool
        if tool_name == 'get_weather' and tool_input_json:
            location = tool_input_json.get('location')
            if location:
                with st.spinner(f'Getting weather for {location}...'):
                    weather_info, weather_icon = get_weather(location)
                
                # Add tool use to conversation messages using your original format
                assistant_message["content_list"] = [
                    {
                        "type": "tool_use",
                        "tool_use": {
                            "tool_use_id": tool_use_id,
                            "name": tool_name,
                            "input": tool_input_json
                        }
                    }
                ]
                
                st.session_state.conversation_messages.append(assistant_message)
                
                # Add tool result message using your original format
                tool_result_message = {
                    'role': 'user',
                    'content': f"Tool result for weather query: {location}",  # Ensure non-empty content
                    'content_list': [
                        {
                            'type': 'tool_results',
                            'tool_results': {
                                'tool_use_id': tool_use_id,
                                'name': tool_name,
                                'content': [
                                    {
                                        'type': 'text',
                                        'text': weather_info
                                    }
                                ]
                            } 
                        }
                    ]
                }
                
                st.session_state.conversation_messages.append(tool_result_message)
                
                # Get Claude's final response with weather data
                with st.spinner("Generating weather report..."):
                    final_text, _, _, _ = call_snowflake_claude(st.session_state.conversation_messages)
                
                if final_text:
                    with st.chat_message("assistant"):
                        st.markdown(final_text)
                        if weather_icon and weather_icon.startswith('//'):
                            weather_icon = 'https:' + weather_icon
                        if weather_icon:
                            st.image(weather_icon, width=100)
                    
                    # Store the complete response in session state
                    final_assistant_message = {
                        "role": "assistant", 
                        "content": final_text
                    }
                    if weather_icon:
                        final_assistant_message["icon"] = weather_icon
                    
                    st.session_state.messages.append(final_assistant_message)
                    st.session_state.conversation_messages.append({
                        "role": "assistant", 
                        "content": final_text if final_text else "Here's your weather information."
                    })
                else:
                    # Fallback if final response fails
                    fallback_response = f"Here's the current weather for {location}: {weather_info}"
                    with st.chat_message("assistant"):
                        st.markdown(fallback_response)
                        if weather_icon:
                            if weather_icon.startswith('//'):
                                weather_icon = 'https:' + weather_icon
                            st.image(weather_icon, width=100)
                    
                    fallback_assistant_message = {
                        "role": "assistant", 
                        "content": fallback_response
                    }
                    if weather_icon:
                        fallback_assistant_message["icon"] = weather_icon
                    
                    st.session_state.messages.append(fallback_assistant_message)
                    st.session_state.conversation_messages.append({
                        "role": "assistant", 
                        "content": fallback_response if fallback_response else "Weather information retrieved."
                    })
            else:
                st.error("No location provided by the tool")
                st.session_state.messages.append({"role": "assistant", "content": text})
                st.session_state.conversation_messages.append({
                    "role": "assistant", 
                    "content": text if text else "I've processed your request."
                })
        else:
            # No tool use, just add the response
            st.session_state.messages.append({"role": "assistant", "content": text})
            st.session_state.conversation_messages.append({
                "role": "assistant", 
                "content": text if text else "I've processed your request."
            })

if __name__ == "__main__":
    main()