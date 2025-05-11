from vonage import Vonage, Auth, HttpClientOptions

# Create an Auth instance
auth = Auth(api_key='your_api_key', api_secret='your_api_secret')

# Create HttpClientOptions instance
# (not required unless you want to change options from the defaults)
options = HttpClientOptions(api_host='api.nexmo.com', timeout=30)

# Create a Vonage instance
vonage = Vonage(auth=auth, http_client_options=options)

from vonage_voice import CreateCallRequest, Talk

ncco = [Talk(text='Hello world', loop=3, language='en-GB')]

call = CreateCallRequest(
    to=[{'type': 'phone', 'number': '1234567890'}],
    ncco=ncco,
    random_from_number=True,
)

response = vonage.voice.create_call(call)
print(response.model_dump())