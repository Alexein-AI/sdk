import type { INodeProperties } from 'n8n-workflow';

// Each operation's value is the route it calls, /v1/memory/<value>.
const show = (...operation: string[]) => ({
	displayOptions: { show: { resource: ['memory'], operation } },
});

export const operations: INodeProperties[] = [
	{
		displayName: 'Resource',
		name: 'resource',
		type: 'options',
		noDataExpression: true,
		options: [{ name: 'Memory', value: 'memory' }],
		default: 'memory',
	},
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['memory'] } },
		options: [
			{
				name: 'Add',
				value: 'add',
				description: 'Remember a message, note or document',
				action: 'Add to memory',
			},
			{
				name: 'Correct',
				value: 'correct',
				description: 'Retract one fact for good, optionally saying what is true instead',
				action: 'Correct a fact',
			},
			{
				name: 'Find Phrase',
				value: 'grep',
				description: 'Every passage holding an exact phrase, ignoring case',
				action: 'Find an exact phrase in memory',
			},
			{
				name: 'Forget',
				value: 'forget',
				description: 'Erase every copy of items, sessions, threads or events, with a receipt',
				action: 'Forget from memory',
			},
			{
				name: 'Get History',
				value: 'history',
				description: 'Every dated value recorded for one subject',
				action: 'Get the history of a subject',
			},
			{
				name: 'Get Latest',
				value: 'latest',
				description: 'The newest passages, or every passage between two dates',
				action: 'Get the latest passages',
			},
			{
				name: 'Get Lineage',
				value: 'lineage',
				description: 'What an item became, or what a fact came from',
				action: 'Get the lineage of an item',
			},
			{
				name: 'Get Overview',
				value: 'overview',
				description: "The shape of this end user's memory and its counts",
				action: 'Get an overview of memory',
			},
			{
				name: 'Get Status',
				value: 'status',
				description: 'How far each added item has got: accepted, landed, read or folded',
				action: 'Get the status of added items',
			},
			{
				name: 'Get Surrounding Passages',
				value: 'around',
				description: 'The passages either side of one passage, in the same thread',
				action: 'Get passages around a passage',
			},
			{
				name: 'Get Versions',
				value: 'versions',
				description: "An added item's versions, and when and why it went",
				action: 'Get the versions of an item',
			},
			{
				name: 'List',
				value: 'ls',
				description: 'What is under a path a result gave you',
				action: 'List what is under a path',
			},
			{
				name: 'Read',
				value: 'read',
				description: 'One passage, whole, by the path a result gave you',
				action: 'Read a passage',
			},
			{
				name: 'Search',
				value: 'search',
				description: 'What memory holds for a question, in plain words',
				action: 'Search memory',
			},
		],
		default: 'search',
	},
	{
		displayName: 'End User',
		name: 'endUser',
		type: 'string',
		required: true,
		default: '',
		placeholder: 'e.g. user_42',
		description:
			"Your ID for the person whose memory this is, usually an expression from the trigger, such as the Telegram user. Each end user has a memory of their own. Letters, digits, '.', '_' and '-', starting with a letter or digit. Up to 35 characters always fits.",
	},
];

export const fields: INodeProperties[] = [
	// Add
	{
		displayName: 'Text',
		name: 'text',
		type: 'string',
		typeOptions: { rows: 4 },
		required: true,
		default: '',
		...show('add'),
		description: 'What to remember: a message, a note, or a whole document',
	},
	{
		displayName: 'Kind',
		name: 'kind',
		type: 'options',
		options: [
			{
				name: 'Document',
				value: 'document',
				description: 'A whole text, such as a file or a page',
			},
			{ name: 'Message', value: 'message', description: 'One turn of a conversation' },
			{ name: 'Note', value: 'note', description: 'A fact on its own' },
		],
		default: 'message',
		...show('add'),
	},
	{
		displayName: 'Wait Until Searchable',
		name: 'wait',
		type: 'boolean',
		default: false,
		...show('add'),
		description:
			"Whether to wait, up to 10 seconds, until the items can be found; the output's pending counts any not yet searchable. Off, an add is accepted at once and searchable a moment later.",
	},
	{
		displayName: 'Additional Fields',
		name: 'additionalFields',
		type: 'collection',
		placeholder: 'Add Field',
		default: {},
		...show('add'),
		options: [
			{
				displayName: 'About',
				name: 'about',
				type: 'string',
				default: '',
				placeholder: 'project:atlas, customer:acme',
				description: 'Work this item names, as kind:name, separated by commas',
			},
			{
				displayName: 'Author',
				name: 'author',
				type: 'string',
				default: '',
				description: 'Who said or wrote it',
			},
			{
				displayName: 'Expires',
				name: 'expires',
				type: 'dateTime',
				default: '',
				description: 'When it stops being true. It is erased then.',
			},
			{
				displayName: 'Item ID',
				name: 'id',
				type: 'string',
				default: '',
				description:
					'Your ID for this item. The same ID again is an edit of it: use it to fix the same statement, and a new ID when something changes.',
			},
			{
				displayName: 'Metadata',
				name: 'metadata',
				type: 'json',
				default: '{}',
				description: 'Your own JSON, kept with the item',
			},
			{
				displayName: 'Role',
				name: 'role',
				type: 'string',
				default: '',
				placeholder: 'user',
				description: "The speaker's role in a conversation, such as user or assistant",
			},
			{
				displayName: 'Session',
				name: 'session',
				type: 'string',
				default: '',
				description: 'Groups messages into one conversation',
			},
			{
				displayName: 'Title',
				name: 'title',
				type: 'string',
				default: '',
				description: "A document's title",
			},
			{
				displayName: 'When',
				name: 'at',
				type: 'dateTime',
				default: '',
				description: 'When it was said or written. Now when empty.',
			},
		],
	},

	// Search
	{
		displayName: 'Query',
		name: 'query',
		type: 'string',
		required: true,
		default: '',
		...show('search'),
		description: 'The question, in plain words',
	},
	{
		displayName: 'Fast',
		name: 'fast',
		type: 'boolean',
		default: false,
		...show('search'),
		description:
			'Whether to skip the relevance check: free and quicker, a little less precise. For replies that cannot wait.',
	},
	{
		displayName: 'Options',
		name: 'searchOptions',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		...show('search'),
		options: [
			{
				displayName: 'After',
				name: 'after',
				type: 'dateTime',
				default: '',
				description: 'Only memory from this day on',
			},
			{
				displayName: 'Before',
				name: 'before',
				type: 'dateTime',
				default: '',
				description: 'Only memory from before this day',
			},
			{
				displayName: 'Context Length',
				name: 'contextLength',
				type: 'number',
				typeOptions: { minValue: 200 },
				default: 4000,
				description: 'The longest the context output may be, in characters',
			},
			{
				displayName: 'Scope',
				name: 'scope',
				type: 'string',
				default: '',
				placeholder: 'passages/memory/messages',
				description: 'A path prefix to search under',
			},
		],
	},

	// History
	{
		displayName: 'Subject',
		name: 'subject',
		type: 'string',
		required: true,
		default: '',
		...show('history'),
		description: 'Who or what to get the history of, such as a person or a project',
	},
	{
		displayName: 'Attribute',
		name: 'attribute',
		type: 'string',
		default: '',
		...show('history'),
		placeholder: 'home_city',
		description: 'Only this attribute of the subject. Every attribute when empty.',
	},

	// Latest
	{
		displayName: 'Limit',
		name: 'k',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 50 },
		default: 10,
		...show('latest'),
		description: 'Max number of results to return',
	},
	{
		displayName: 'Options',
		name: 'latestOptions',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		...show('latest'),
		options: [
			{
				displayName: 'After',
				name: 'after',
				type: 'dateTime',
				default: '',
				description: 'Every passage from this day on, rather than the newest few',
			},
			{
				displayName: 'Before',
				name: 'before',
				type: 'dateTime',
				default: '',
				description: 'Every passage from before this day',
			},
			{
				displayName: 'Place',
				name: 'place',
				type: 'string',
				default: '',
				description:
					'Where to look: a name from a passage path under passages/, such as memory or notes. Everywhere when empty.',
			},
		],
	},

	// Find Phrase
	{
		displayName: 'Phrase',
		name: 'pattern',
		type: 'string',
		required: true,
		default: '',
		...show('grep'),
		description: 'The exact phrase to find, ignoring case',
	},
	{
		displayName: 'Limit',
		name: 'limit',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 50 },
		default: 50,
		...show('grep'),
		description: 'Max number of results to return',
	},
	{
		displayName: 'Scope',
		name: 'scope',
		type: 'string',
		default: '',
		...show('grep'),
		description: 'A path prefix to look under. Everywhere when empty.',
	},

	// Read and List
	{
		displayName: 'Path',
		name: 'path',
		type: 'string',
		required: true,
		default: '',
		...show('read'),
		description: 'A path from another result, such as passages/memory/messages/th_…/p_0001.md',
	},
	{
		displayName: 'Path',
		name: 'path',
		type: 'string',
		default: '',
		...show('ls'),
		description: 'A directory from another result. The top when empty.',
	},

	// Surrounding passages
	{
		displayName: 'Passage ID',
		name: 'passageId',
		type: 'string',
		required: true,
		default: '',
		...show('around'),
		description: 'A passage ID from another result, such as th_…/p_0001',
	},
	{
		displayName: 'Width',
		name: 'width',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 5 },
		default: 2,
		...show('around'),
		description: 'How many passages to get on each side',
	},

	// Versions, Lineage
	{
		displayName: 'Item ID',
		name: 'itemId',
		type: 'string',
		required: true,
		default: '',
		...show('versions'),
		description: 'The ID the item was added with',
	},
	{
		displayName: 'ID',
		name: 'lineageId',
		type: 'string',
		required: true,
		default: '',
		...show('lineage'),
		description: 'An item ID, an event ID (ev_…), or a fact ID from search (th_…#r…)',
	},

	// Status
	{
		displayName: 'IDs',
		name: 'ids',
		type: 'string',
		required: true,
		default: '',
		...show('status'),
		description: 'Item or event IDs, separated by commas. Up to 500.',
	},

	// Forget
	{
		displayName: 'Item IDs',
		name: 'items',
		type: 'string',
		default: '',
		...show('forget'),
		description: 'Items to forget, by the IDs they were added with, separated by commas',
	},
	{
		displayName: 'Sessions',
		name: 'sessions',
		type: 'string',
		default: '',
		...show('forget'),
		description: 'Whole sessions to forget, separated by commas',
	},
	{
		displayName: 'Threads',
		name: 'threads',
		type: 'string',
		default: '',
		...show('forget'),
		description: 'Thread IDs (th_…) to forget, separated by commas',
	},
	{
		displayName: 'Events',
		name: 'events',
		type: 'string',
		default: '',
		...show('forget'),
		description: 'Event IDs (ev_…) to forget, separated by commas',
	},

	// Correct
	{
		displayName: 'Fact ID',
		name: 'recordId',
		type: 'string',
		required: true,
		default: '',
		...show('correct'),
		description: 'The ID search gave the fact, such as th_…#r…',
	},
	{
		displayName: 'Replacement',
		name: 'replacement',
		type: 'string',
		default: '',
		...show('correct'),
		description: 'What is true instead, kept as a note. Nothing when empty.',
	},
];
