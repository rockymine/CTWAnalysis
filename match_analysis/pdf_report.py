"""
CTW PDF Report Generator

Creates professional PDF reports for match analysis and classification.
"""

from typing import List
from collections import Counter, defaultdict
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from .preprocessing import LifeSegment
from .segment_classifier import SegmentClassification, MapCharacteristics


class PDFReportGenerator:
    """Generate PDF reports for CTW analysis."""

    def __init__(self, output_path: str):
        """
        Initialize PDF report generator.

        Args:
            output_path: Path to output PDF file
        """
        self.output_path = output_path
        self.doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )
        self.styles = getSampleStyleSheet()
        self.story = []

        # Custom styles
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=30,
            alignment=TA_CENTER
        ))
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#34495E'),
            spaceAfter=12,
            spaceBefore=12,
            borderWidth=1,
            borderColor=colors.HexColor('#BDC3C7'),
            borderPadding=5
        ))
        self.styles.add(ParagraphStyle(
            name='SubHeader',
            parent=self.styles['Heading3'],
            fontSize=12,
            textColor=colors.HexColor('#7F8C8D'),
            spaceAfter=8,
            spaceBefore=8
        ))

    def add_title(self, title: str):
        """Add main title to report."""
        self.story.append(Paragraph(title, self.styles['CustomTitle']))
        self.story.append(Spacer(1, 0.2*inch))

    def add_section(self, title: str):
        """Add section header."""
        self.story.append(Paragraph(title, self.styles['SectionHeader']))
        self.story.append(Spacer(1, 0.1*inch))

    def add_subsection(self, title: str):
        """Add subsection header."""
        self.story.append(Paragraph(title, self.styles['SubHeader']))

    def add_text(self, text: str):
        """Add regular text."""
        self.story.append(Paragraph(text, self.styles['Normal']))
        self.story.append(Spacer(1, 0.1*inch))

    def add_table(self, data: List[List[str]], col_widths=None, header_row=True):
        """
        Add a table to the report.

        Args:
            data: List of lists containing table data
            col_widths: Optional list of column widths
            header_row: Whether first row is a header
        """
        table = Table(data, colWidths=col_widths)

        style = [
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1 if header_row else 0), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')])
        ]

        if header_row:
            style.extend([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495E')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
            ])

        table.setStyle(TableStyle(style))
        self.story.append(table)
        self.story.append(Spacer(1, 0.15*inch))

    def add_page_break(self):
        """Add a page break."""
        self.story.append(PageBreak())

    def generate(self):
        """Build the PDF document."""
        self.doc.build(self.story)


def generate_classification_pdf(
    life_segments: List[LifeSegment],
    classifications: List[SegmentClassification],
    map_chars: MapCharacteristics,
    config: dict,
    output_path: str
) -> None:
    """
    Generate PDF classification report.

    Args:
        life_segments: List of LifeSegment objects
        classifications: List of SegmentClassification objects
        map_chars: MapCharacteristics object
        config: Configuration dictionary
        output_path: Path to output PDF file
    """
    pdf = PDFReportGenerator(output_path)

    # Title
    pdf.add_title("CTW Life Segment Classification Report")

    # Match information
    pdf.add_section("Match Information")
    match_info = [
        ['Map', config['data_files']['map_name']],
        ['Match File', config['data_files']['match_file']],
        ['Total Segments', str(len(life_segments))],
        ['Total Players', str(len(set(seg.player_id for seg in life_segments)))]
    ]
    pdf.add_table(match_info, col_widths=[2*inch, 4*inch], header_row=False)

    # Map characteristics
    pdf.add_section("Map Characteristics")
    map_info = [
        ['Characteristic', 'Value'],
        ['Midpoint Axis', map_chars.midpoint_axis.upper()],
        ['Midpoint Coordinate', f'{map_chars.midpoint_coord:.1f}'],
        ['Red Team Side', 'Positive' if map_chars.red_side_positive else 'Negative'],
        ['Skybridge Height', f'Y = {map_chars.skybridge_height:.1f}'],
        ['Ground Level', f'Y = {map_chars.ground_level:.1f}'],
        ['Tunnel Threshold', f'Y ≤ {map_chars.tunnel_threshold:.1f}']
    ]
    pdf.add_table(map_info, col_widths=[2.5*inch, 3.5*inch])

    # Role distribution
    pdf.add_section("Role Distribution")
    role_counts = Counter(c.primary_role for c in classifications)
    total = len(classifications)

    role_data = [['Role', 'Segments', 'Percentage']]
    for role, count in role_counts.most_common():
        percentage = (count / total) * 100
        role_data.append([role, str(count), f'{percentage:.1f}%'])

    pdf.add_table(role_data, col_widths=[2.5*inch, 1.5*inch, 1.5*inch])

    # Page break
    pdf.add_page_break()

    # Role definitions
    pdf.add_section("Role Definitions")

    role_definitions = {
        'WOOL_RUNNER': 'Carries wool from enemy base to own base',
        'SKYBRIDGE_CONTROLLER': 'Stays on skybridge (high altitude), controls lanes with kills',
        'ATTACKER_STEALTH': 'Uses tunnels to infiltrate enemy territory',
        'RUSHER': 'Fast movement to enemy side immediately after spawn',
        'ATTACKER_AGGRESSIVE': 'Pushes enemy side with high kill count',
        'ATTACKER_PASSIVE': 'Moves to enemy side without many kills',
        'CAMPER': 'Minimal movement, waits for enemies and gets kills',
        'MID_CONTROLLER': 'Controls the middle area between territories',
        'BASE_DEFENDER': 'Guards own spawn area',
        'DEFENDER': 'Stays primarily on own side',
        'FLANKER': 'Moves around map edges with high mobility',
        'ROAMER': 'General roaming without clear pattern'
    }

    for role, count in role_counts.most_common():
        if role in role_definitions:
            pdf.add_text(f"<b>{role}:</b> {role_definitions[role]}")

    # Team-specific distribution
    pdf.add_page_break()
    pdf.add_section("Team-Specific Role Distribution")

    for team in ['red', 'blue']:
        team_segments = [seg for seg in life_segments if seg.team == team]
        team_classifications = [classifications[i] for i, seg in enumerate(life_segments) if seg.team == team]

        if not team_classifications:
            continue

        pdf.add_subsection(f"{team.upper()} TEAM")

        team_role_counts = Counter(c.primary_role for c in team_classifications)
        team_total = len(team_classifications)

        team_data = [['Role', 'Segments', 'Percentage']]
        for role, count in team_role_counts.most_common(10):
            percentage = (count / team_total) * 100
            team_data.append([role, str(count), f'{percentage:.1f}%'])

        pdf.add_table(team_data, col_widths=[2.5*inch, 1.5*inch, 1.5*inch])

    # Top players by role
    pdf.add_page_break()
    pdf.add_section("Top Players by Role")

    # Group by player and role
    player_roles = defaultdict(lambda: defaultdict(int))
    player_kills = defaultdict(int)
    player_team = {}

    for i, seg in enumerate(life_segments):
        classification = classifications[i]
        player_roles[seg.player_id][classification.primary_role] += 1
        player_kills[seg.player_id] += classification.kills
        player_team[seg.player_id] = seg.team

    # Show top players for major roles
    major_roles = [role for role, count in role_counts.most_common(8) if count > 10]

    for role in major_roles[:6]:  # Limit to 6 roles for space
        pdf.add_subsection(role)

        # Find specialists
        role_specialists = []
        for player_id, roles in player_roles.items():
            role_count = roles[role]
            total_segments = sum(roles.values())
            if role_count > 0:
                ratio = role_count / total_segments
                role_specialists.append((player_id, role_count, total_segments, ratio, player_team[player_id]))

        role_specialists.sort(key=lambda x: x[1], reverse=True)

        specialist_data = [['Player', 'Team', 'Segments', 'Total', 'Ratio', 'Kills']]
        for player_id, role_count, total, ratio, team in role_specialists[:5]:
            specialist_data.append([
                f'{player_id:.0f}',
                team,
                str(role_count),
                str(total),
                f'{ratio*100:.1f}%',
                str(player_kills[player_id])
            ])

        pdf.add_table(specialist_data, col_widths=[0.8*inch, 0.8*inch, 1*inch, 0.8*inch, 0.8*inch, 0.8*inch])

    # Example segments
    pdf.add_page_break()
    pdf.add_section("Example Segments")

    shown_roles = Counter()
    examples_per_role = 1

    for i, seg in enumerate(life_segments):
        classification = classifications[i]
        role = classification.primary_role

        if role not in major_roles or shown_roles[role] >= examples_per_role:
            continue

        shown_roles[role] += 1

        pdf.add_subsection(f"{role} Example")

        example_data = [
            ['Metric', 'Value'],
            ['Player', f'{seg.player_id:.0f} ({seg.team} team)'],
            ['Duration', f'{seg.end_time - seg.spawn_time:.1f}s'],
            ['Description', classification.description],
            ['Time on Own Side', f'{classification.time_on_own_side:.1f}s ({classification.time_on_own_side/(seg.end_time - seg.spawn_time)*100:.0f}%)'],
            ['Time on Enemy Side', f'{classification.time_on_enemy_side:.1f}s ({classification.time_on_enemy_side/(seg.end_time - seg.spawn_time)*100:.0f}%)'],
            ['Time at Skybridge', f'{classification.time_at_skybridge:.1f}s'],
            ['Total Distance', f'{classification.total_distance:.1f} blocks'],
            ['Average Speed', f'{classification.avg_speed:.2f} blocks/s'],
            ['Kills', str(classification.kills)],
            ['Deaths', str(classification.deaths)],
            ['End Reason', seg.end_reason]
        ]

        pdf.add_table(example_data, col_widths=[2*inch, 4*inch], header_row=True)

    # Generate PDF
    pdf.generate()
    print(f"PDF report saved to: {output_path}")


def generate_match_summary_pdf(
    life_segments: List[LifeSegment],
    player_stats,
    config: dict,
    output_path: str
) -> None:
    """
    Generate PDF match summary report.

    Args:
        life_segments: List of LifeSegment objects
        player_stats: DataFrame with player statistics
        config: Configuration dictionary
        output_path: Path to output PDF file
    """
    pdf = PDFReportGenerator(output_path)

    # Title
    pdf.add_title("CTW Match Summary Report")

    # Match information
    pdf.add_section("Match Information")
    match_info = [
        ['Map', config['data_files']['map_name']],
        ['Match File', config['data_files']['match_file']],
        ['Total Players', str(len(set(seg.player_id for seg in life_segments)))],
        ['Total Life Segments', str(len(life_segments))]
    ]
    pdf.add_table(match_info, col_widths=[2*inch, 4*inch], header_row=False)

    # Overall statistics
    pdf.add_section("Overall Statistics")

    team_counts = Counter(seg.team for seg in life_segments)
    end_reasons = Counter(seg.end_reason for seg in life_segments)

    total_kills = sum(seg.to_dict()['kills'] for seg in life_segments)
    total_deaths = sum(seg.to_dict()['deaths'] for seg in life_segments)
    total_wool_touches = sum(seg.to_dict()['wool_touches'] for seg in life_segments)
    total_wool_captures = sum(seg.to_dict()['wool_captures'] for seg in life_segments)

    stats_data = [
        ['Metric', 'Value'],
        ['Total Kills', str(total_kills)],
        ['Total Deaths', str(total_deaths)],
        ['Wool Touches', str(total_wool_touches)],
        ['Wool Captures', str(total_wool_captures)],
        ['', ''],
        ['Red Team Segments', str(team_counts['red'])],
        ['Blue Team Segments', str(team_counts['blue'])],
    ]
    pdf.add_table(stats_data, col_widths=[2.5*inch, 3.5*inch], header_row=True)

    # Top players
    pdf.add_page_break()
    pdf.add_section("Top 20 Players by Kills")

    player_data = [['Player', 'Team', 'Segments', 'Kills', 'Deaths', 'K/D', 'Wool']]
    for _, row in player_stats.head(20).iterrows():
        kd_ratio = row['total_kills'] / row['total_deaths'] if row['total_deaths'] > 0 else row['total_kills']
        player_data.append([
            f"{row['player_id']:.0f}",
            row['primary_team'],
            str(row['total_segments']),
            str(row['total_kills']),
            str(row['total_deaths']),
            f'{kd_ratio:.2f}',
            str(row['total_wool_captures'])
        ])

    pdf.add_table(player_data, col_widths=[0.7*inch, 0.7*inch, 0.9*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch])

    # Team statistics
    pdf.add_page_break()
    pdf.add_section("Team Statistics")

    for team in ['red', 'blue']:
        team_segments = [seg for seg in life_segments if seg.team == team]
        if not team_segments:
            continue

        team_kills = sum(seg.to_dict()['kills'] for seg in team_segments)
        team_deaths = sum(seg.to_dict()['deaths'] for seg in team_segments)
        team_wool_touches = sum(seg.to_dict()['wool_touches'] for seg in team_segments)
        team_wool_captures = sum(seg.to_dict()['wool_captures'] for seg in team_segments)
        team_players = len(set(seg.player_id for seg in team_segments))

        pdf.add_subsection(f"{team.upper()} TEAM")

        team_data = [
            ['Metric', 'Value'],
            ['Players', str(team_players)],
            ['Life Segments', str(len(team_segments))],
            ['Total Kills', str(team_kills)],
            ['Total Deaths', str(team_deaths)],
            ['K/D Ratio', f'{team_kills/team_deaths:.2f}' if team_deaths > 0 else 'N/A'],
            ['Wool Touches', str(team_wool_touches)],
            ['Wool Captures', str(team_wool_captures)]
        ]

        pdf.add_table(team_data, col_widths=[2*inch, 2*inch], header_row=True)

    # Generate PDF
    pdf.generate()
    print(f"PDF summary saved to: {output_path}")
