"""Validate model summaries and keep the Markdown representation for existing readers."""


def validate_summary_structure(summary):
    if not isinstance(summary, dict) or summary.keys() != {'overview', 'key_points', 'limitations'}:
        raise ValueError('invalid summary structure')
    overview, points, limitations = (summary[key] for key in ('overview', 'key_points', 'limitations'))
    if not isinstance(overview, str) or not overview.strip() or not isinstance(limitations, str):
        raise ValueError('invalid summary text')
    if not isinstance(points, list) or any(
        not isinstance(point, str) or not point.strip() or point.splitlines() != [point] for point in points
    ):
        raise ValueError('invalid summary key points')


def summary_markdown(summary):
    validate_summary_structure(summary)
    points = '\n'.join(f'- {point.strip()}' for point in summary['key_points'])
    return '\n\n'.join(filter(None, (summary['overview'].strip(), points, summary['limitations'].strip())))


def summary_fields(output, strategy):
    if not isinstance(output, dict) or not isinstance(output.get('notes'), str) or not output['notes'].strip():
        raise ValueError('invalid notes')
    summary = output.get('summary')
    fields = {'summary': summary, 'notes': output['notes']}
    if strategy.get('summary_format') == 'structured':
        fields.update(summary=summary_markdown(summary), summary_structure=summary)
    elif not isinstance(summary, str) or not summary.strip():
        raise ValueError('invalid legacy summary')
    return fields
