"""MCP file interface. Routing machine is always required; identity is internal."""
def tool(name, description, fields, required):
    return {'name': name, 'description': description, 'inputSchema': {
        'type': 'object', 'additionalProperties': False,
        'required': ['machine'] + required,
        'properties': {'machine': {'type': 'string', 'enum': ['vps', 'mac_noleggio', 'mac_mio']}, **fields}}}


PATH = {'type': 'string', 'description': 'Absolute path within the allowed project roots.'}
FILE_TOOLS = [
    tool('read_file', 'Read UTF-8 text in allowed roots; offset/length select lines, max_bytes selects bytes. Do not combine the two modes. Negative offset reads from the end.',
         {'path': PATH, 'offset': {'type': 'integer', 'default': 0},
          'length': {'type': 'integer', 'minimum': 0, 'maximum': 10000, 'default': 1000},
          'max_bytes': {'type': 'integer', 'minimum': 1, 'maximum': 524288}}, ['path']),
    tool('read_multiple_files', 'Read up to 20 text files; each result has its own success or error.',
         {'paths': {'type': 'array', 'items': PATH, 'minItems': 1, 'maxItems': 20}}, ['paths']),
    tool('write_file', 'Write text with durable rollback. Append bounded chunks to build a larger file.',
         {'path': PATH, 'content': {'type': 'string'},
          'mode': {'type': 'string', 'enum': ['rewrite', 'append'], 'default': 'rewrite'}}, ['path', 'content']),
    tool('edit_block', 'Replace exact text only when occurrence count matches; otherwise leave file unchanged.',
         {'file_path': PATH, 'old_string': {'type': 'string', 'minLength': 1},
          'new_string': {'type': 'string'},
          'expected_replacements': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 1}},
         ['file_path', 'old_string', 'new_string']),
    tool('list_directory', 'Bounded recursive listing with [FILE] and [DIR] prefixes; links are not followed.',
         {'path': PATH, 'depth': {'type': 'integer', 'minimum': 0, 'maximum': 8, 'default': 2}}, ['path']),
    tool('create_directory', 'Create intermediate directories with persistent rollback.', {'path': PATH}, ['path']),
    tool('move_file', 'Move or rename a regular file without replacing an existing destination; persistent rollback.',
         {'source': PATH, 'destination': PATH}, ['source', 'destination']),
    tool('get_file_info', 'Get size, permissions, timestamps and text line count; unavailable birth time is null.',
         {'path': PATH}, ['path']),
    tool('rollback_file', 'Undo a committed operation if its resulting files have not changed; persistent across restarts.',
         {'operation_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'}}, ['operation_id'])
]
FILE_NAMES = {t['name'] for t in FILE_TOOLS}


def install_schema(existing):
    return [t for t in existing if t['name'] not in FILE_NAMES] + FILE_TOOLS
