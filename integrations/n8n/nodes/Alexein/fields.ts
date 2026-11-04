import type { INodeProperties } from 'n8n-workflow';

// Each operation's value is the route it calls, /v2/memory/<value>, but for `openItems`
// (open_items) and `deleteUser` (users/delete): `route()` in requests.ts.
const show = (...operation: string[]) => ({
	displayOptions: { show: { resource: ['memory'], operation } },
});

// A paged operation's fields when it returns one page: the page's length, and where it starts.
const onePage = (operation: string) => ({
	displayOptions: { show: { resource: ['memory'], operation: [operation], returnAll: [false] } },
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
				description: "Save a message, note or document to this app user's memory",
				action: 'Add to memory',
			},
			{
				name: 'Correct',
				value: 'correct',
				description:
					'Retract one fact for good, by its ref, optionally saying what is true instead',
				action: 'Correct a fact',
			},
			{
				name: 'Delete App User',
				value: 'deleteUser',
				description:
					"Erase this app user's whole memory: every item, fact and version. Not undone.",
				action: 'Delete an app user',
			},
			{
				name: 'Export',
				value: 'export',
				description:
					'Everything memory holds for this app user: items as added, what connected apps delivered, and the facts learned',
				action: 'Export memory',
			},
			{
				name: 'Find Phrase',
				value: 'grep',
				description:
					'Excerpts holding an exact phrase, ignoring case: for a name, an ID or an error code a search would blur',
				action: 'Find an exact phrase in memory',
			},
			{
				name: 'Forget',
				value: 'forget',
				description:
					'Erase items, sessions, or memories by ref, with every copy and everything learned from them',
				action: 'Forget from memory',
			},
			{
				name: 'Get History',
				value: 'history',
				description:
					'Every value a subject was stated to have, oldest first, with when each was said: what was true, and what changed',
				action: 'Get the history of a subject',
			},
			{
				name: 'Get Item',
				value: 'item',
				description: 'One added item by its ID, as it was given, and whether it is searchable yet',
				action: 'Get an added item',
			},
			{
				name: 'Get Latest',
				value: 'latest',
				description:
					'The most recent excerpts, newest first: what just happened, everywhere or in one place, or between two dates',
				action: 'Get the latest excerpts',
			},
			{
				name: 'Get Open Items',
				value: 'openItems',
				description:
					'Issues and pull requests still open, newest first, and follow-ups: open asks nobody answered',
				action: 'Get open items',
			},
			{
				name: 'Get Sources',
				value: 'sources',
				description: 'What each connected app delivered to this memory, and the newest',
				action: 'Get connected sources',
			},
			{
				name: 'Get Status',
				value: 'status',
				description:
					'How far each added item has got: queued, stored (searchable), processed or unknown',
				action: 'Get the status of added items',
			},
			{
				name: 'Get Summary',
				value: 'summary',
				description:
					'What this memory holds, in brief: how many items, the span they cover, connected sources and the known lines',
				action: 'Get a summary of memory',
			},
			{
				name: 'Get Surrounding Excerpts',
				value: 'around',
				description: 'The excerpts just before and after one, from the same conversation, in order',
				action: 'Get excerpts around an excerpt',
			},
			{
				name: 'Get Versions',
				value: 'versions',
				description: 'Every version of one added item, oldest first, and when and why it went',
				action: 'Get the versions of an item',
			},
			{
				name: 'List App Users',
				value: 'users',
				description:
					"Every app user of this key's project with memory, with how many items and facts each holds",
				action: 'List app users',
			},
			{
				name: 'List Facts',
				value: 'facts',
				description: 'The facts memory learned, newest first: each in words, dated, with its ref',
				action: 'List facts',
			},
			{
				name: 'List Items',
				value: 'items',
				description: 'The items added to this memory, newest first, as they were given',
				action: 'List added items',
			},
			{
				name: 'Open',
				value: 'open',
				description:
					'One memory whole, by the ref a result gave: an excerpt in full, or a fact with the excerpts it was learned from',
				action: 'Open a memory by its ref',
			},
			{
				name: 'Search',
				value: 'search',
				description:
					'What memory holds for a plain-words question: known lines, facts and excerpts, each with a ref',
				action: 'Search memory',
			},
		],
		default: 'search',
	},
	{
		displayName: 'App User',
		name: 'user',
		type: 'string',
		required: true,
		default: '',
		placeholder: 'e.g. user_42',
		displayOptions: { hide: { operation: ['users'] } },
		description:
			"Your ID for the person whose memory this is, usually an expression from the trigger, such as the Telegram user. Each app user has a memory of their own. 1 to 35 letters, digits, '.', '_' and '-', beginning with a letter or digit.",
	},
];

// Narrowing a read by where a memory came from. `provider` and `source` are what a connected app
// delivered; `kind` is an item's kind or a connected app's own.
const origin: INodeProperties[] = [
	{
		displayName: 'Kind',
		name: 'kind',
		type: 'string',
		default: '',
		placeholder: 'note, pull_request',
		description:
			"Only these kinds, separated by commas: message, document or note for items you added, or a connected app's own, such as pull_request. Up to 8.",
	},
	{
		displayName: 'Provider',
		name: 'provider',
		type: 'string',
		default: '',
		placeholder: 'github',
		description: 'Only what came from this connected app, such as github or slack',
	},
	{
		displayName: 'Source',
		name: 'source',
		type: 'string',
		default: '',
		description:
			"Only this source within a connected app, as the excerpt's first line names it. With Provider.",
	},
];

const filters: INodeProperties = {
	displayName: 'Filters',
	name: 'filters',
	type: 'json',
	default: '{}',
	description:
		'Only items that match, by author, mentions or metadata keys, combined with AND, OR and NOT, such as {"metadata": {"priority": {"gte": 3}}}. See docs.alexein.ai/concepts/filters.',
};

const after = (description: string): INodeProperties => ({
	displayName: 'After',
	name: 'after',
	type: 'dateTime',
	default: '',
	description,
});

const before = (description: string): INodeProperties => ({
	displayName: 'Before',
	name: 'before',
	type: 'dateTime',
	default: '',
	description,
});

// Return All, Limit and Cursor for a paged operation.
function paged(operation: string, max: number): INodeProperties[] {
	return [
		{
			displayName: 'Return All',
			name: 'returnAll',
			type: 'boolean',
			default: false,
			...show(operation),
			description: 'Whether to return all results or only up to a given limit',
		},
		{
			displayName: 'Limit',
			name: 'limit',
			type: 'number',
			typeOptions: { minValue: 1, maxValue: max },
			default: 50,
			...onePage(operation),
			description: 'Max number of results to return',
		},
		{
			displayName: 'Cursor',
			name: 'cursor',
			type: 'string',
			default: '',
			...onePage(operation),
			description: 'The next of the page before, for the page after it. The first page when empty.',
		},
	];
}

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
			"Whether to wait, briefly, until the items can be found; the output's waiting counts any not yet searchable. Off, an add is accepted at once and searchable a moment later.",
	},
	{
		displayName: 'Redact',
		name: 'redact',
		type: 'boolean',
		default: false,
		...show('add'),
		description:
			'Whether to replace phone numbers, payment cards, IBANs, API keys, passwords and the like in the text, title and metadata with their kind, such as [PHONE], before memory keeps any copy',
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
				description: 'What this item is about, as kind:name, separated by commas',
			},
			{
				displayName: 'Author',
				name: 'author',
				type: 'string',
				default: '',
				description: 'Who said or wrote it: your ID for them, a name, an email or a handle',
			},
			{
				displayName: 'Expires',
				name: 'expires',
				type: 'dateTime',
				default: '',
				description: 'When it stops being true. It is forgotten then.',
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
				description: 'Your own JSON, kept with the item, and what Filters can match',
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
			after('Only memories from this day on'),
			before('Only memories from before this day'),
			{
				displayName: 'Context Length',
				name: 'contextLength',
				type: 'number',
				typeOptions: { minValue: 200 },
				default: 4000,
				description: 'The longest the context output may be, in characters',
			},
			filters,
			...origin,
		],
	},

	// Get History
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
		placeholder: 'home city',
		description: 'Only this attribute of the subject. Every attribute when empty.',
	},

	// Get Latest
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
			after('Every excerpt from this day on, rather than the newest few'),
			before('Every excerpt from before this day'),
			filters,
			...origin,
			{
				displayName: 'Place',
				name: 'place',
				type: 'string',
				default: '',
				description:
					'Where to look, such as messages, documents, notes, or a connected app such as slack. Everywhere when empty.',
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
		displayName: 'Options',
		name: 'grepOptions',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		...show('grep'),
		options: origin,
	},

	// Open, Get Surrounding Excerpts
	{
		displayName: 'Ref',
		name: 'ref',
		type: 'string',
		required: true,
		default: '',
		...show('open', 'around'),
		placeholder: 'mem_…',
		description: "A fact's or an excerpt's ref, from another result",
	},
	{
		displayName: 'Width',
		name: 'width',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 5 },
		default: 2,
		...show('around'),
		description: 'How many excerpts to get on each side',
	},

	// Get Open Items
	{
		displayName: 'Limit',
		name: 'limit',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 50 },
		default: 50,
		...show('openItems'),
		description: 'Max number of results to return',
	},
	{
		displayName: 'Options',
		name: 'openItemsOptions',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		...show('openItems'),
		options: [
			{
				displayName: 'Kind',
				name: 'kind',
				type: 'string',
				default: '',
				placeholder: 'issue, pull_request',
				description: 'Only these kinds, separated by commas, such as issue or pull_request',
			},
			{
				displayName: 'Mine Only',
				name: 'mine',
				type: 'boolean',
				default: true,
				description:
					"Whether to return only the app user's own: what they wrote, are assigned or review",
			},
			{
				displayName: 'Place',
				name: 'place',
				type: 'string',
				default: '',
				description: 'Only this place, such as one repository',
			},
			{
				displayName: 'Provider',
				name: 'provider',
				type: 'string',
				default: '',
				placeholder: 'github',
				description: 'Only what came from this connected app, such as github',
			},
			{
				displayName: 'Within Days',
				name: 'withinDays',
				type: 'number',
				typeOptions: { minValue: 0, maxValue: 3650 },
				default: 0,
				description: 'Only what changed in this many days. Any time when 0.',
			},
		],
	},

	// List Facts, List Items, Export, List App Users
	...paged('facts', 100),
	...paged('items', 200),
	{
		displayName: 'Options',
		name: 'itemsOptions',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		...show('items'),
		options: [filters],
	},
	...paged('export', 500),
	...paged('users', 500),

	// Get Item, Get Versions
	{
		displayName: 'Item ID',
		name: 'itemId',
		type: 'string',
		required: true,
		default: '',
		...show('item', 'versions'),
		description: 'The ID the item was added with',
	},

	// Get Status
	{
		displayName: 'Item IDs',
		name: 'ids',
		type: 'string',
		required: true,
		default: '',
		...show('status'),
		description:
			'The IDs items were added with, or that Add answered, separated by commas. Up to 500.',
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
		description: 'Whole sessions to forget, as items named them, separated by commas',
	},
	{
		displayName: 'Refs',
		name: 'refs',
		type: 'string',
		default: '',
		...show('forget'),
		description:
			"Refs to forget, separated by commas: a fact's forgets the messages it came from and all learned from them; an excerpt's, its whole conversation",
	},

	// Correct
	{
		displayName: 'Ref',
		name: 'ref',
		type: 'string',
		required: true,
		default: '',
		...show('correct'),
		placeholder: 'mem_…',
		description: "The fact's ref, from a search or List Facts",
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
