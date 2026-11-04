import type {
	IAuthenticateGeneric,
	Icon,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

// An API key from the Alexein console. The end user is not part of the credential: it changes
// per item, so it is a field on the node.
export class TwinMemoryApi implements ICredentialType {
	name = 'twinMemoryApi';

	displayName = 'Twin Memory API';

	icon: Icon = { light: 'file:../icons/twinmemory.svg', dark: 'file:../icons/twinmemory.dark.svg' };

	documentationUrl = 'https://docs.alexein.ai/integrations/n8n';

	properties: INodeProperties[] = [
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			required: true,
			default: '',
			description: 'A key from the Alexein console, under API keys. It starts with tm_.',
		},
		{
			displayName: 'Base URL',
			name: 'baseUrl',
			type: 'string',
			required: true,
			default: 'https://api.alexein.ai',
			description: 'The address of the Alexein API',
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

	// GET /v1/me names no end user, so it checks the key before the node has one.
	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{$credentials.baseUrl.replace(/\\/+$/, "")}}',
			url: '/v1/me',
			method: 'GET',
		},
	};
}
