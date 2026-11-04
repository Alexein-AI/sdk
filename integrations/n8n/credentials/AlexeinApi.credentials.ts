import type {
	IAuthenticateGeneric,
	Icon,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

// An API key from the Alexein console. The app user is not part of the credential: it changes per
// item, so it is a field on the node.
export class AlexeinApi implements ICredentialType {
	name = 'alexeinApi';

	displayName = 'Alexein API';

	icon: Icon = { light: 'file:../icons/alexein.svg', dark: 'file:../icons/alexein.dark.svg' };

	documentationUrl = 'https://docs.alexein.ai/integrations/n8n';

	properties: INodeProperties[] = [
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			required: true,
			default: '',
			description:
				'A key from the Alexein console, under API keys. A key that writes, to add, forget, correct or delete.',
		},
		{
			displayName: 'Base URL',
			name: 'baseUrl',
			type: 'string',
			required: true,
			default: 'https://api.alexein.ai',
			description: 'The address of the Alexein API. The node adds /v2 itself.',
		},
	];

	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				Authorization: '=Bearer {{$credentials.apiKey}}',
			},
		},
	};

	// GET /v2/me names no app user, so it checks the key before the node has one. The Base URL is
	// the host: a trailing `/` or `/v2` is dropped, as the node drops it.
	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{$credentials.baseUrl.replace(/(?:\\/v2)?\\/*$/, "")}}',
			url: '/v2/me',
			method: 'GET',
		},
	};
}
