"""Tests for ACL Anthology crawler (src/core/acl_anthology.py)."""

import pytest

from src.core.acl_anthology import (
    ACLAnthologyCollector,
    ACL_VENUES,
    get_acl_venues,
    get_acl_venue_info,
)
from src.models.paper import SourceType, PaperType, Author


class TestACLVenueConfig:
    """Tests for ACL venue configuration."""

    def test_acl_venues_defined(self):
        """Test that all expected ACL venues are defined."""
        expected = ["acl", "emnlp", "naacl", "eacl", "coling", "findings", "tacl", "conll", "lrec"]
        for venue in expected:
            assert venue in ACL_VENUES, f"Missing venue: {venue}"

    def test_get_acl_venues(self):
        """Test get_acl_venues returns list of venue names."""
        venues = get_acl_venues()
        assert isinstance(venues, list)
        assert "acl" in venues
        assert "emnlp" in venues

    def test_get_acl_venue_info(self):
        """Test get_acl_venue_info returns venue details."""
        info = get_acl_venue_info("acl")
        assert info is not None
        assert "full_name" in info
        assert "tier" in info
        assert info["tier"] == 0

    def test_get_acl_venue_info_unknown(self):
        """Test get_acl_venue_info returns None for unknown venue."""
        info = get_acl_venue_info("unknown_venue")
        assert info is None

    def test_venue_tiers(self):
        """Test that venue tiers are correctly assigned."""
        # Tier 0 venues
        assert ACL_VENUES["acl"]["tier"] == 0
        assert ACL_VENUES["emnlp"]["tier"] == 0

        # Tier 1 venues
        assert ACL_VENUES["naacl"]["tier"] == 1
        assert ACL_VENUES["eacl"]["tier"] == 1
        assert ACL_VENUES["coling"]["tier"] == 1


class TestACLAnthologyCollector:
    """Tests for ACLAnthologyCollector class."""

    @pytest.fixture
    def sample_xml_content(self):
        """Sample ACL Anthology XML content."""
        return """<?xml version='1.0' encoding='UTF-8'?>
<collection id="2023.acl">
  <volume id="long" type="proceedings">
    <meta>
      <booktitle>Proceedings of ACL 2023 (Volume 1: Long Papers)</booktitle>
      <address>Toronto, Canada</address>
      <month>July</month>
      <year>2023</year>
      <venue>acl</venue>
    </meta>
    <paper id="1">
      <title>Test Paper Title</title>
      <author><first>John</first><last>Doe</last></author>
      <author><first>Jane</first><last>Smith</last></author>
      <abstract>This is a test abstract for the paper.</abstract>
      <url>2023.acl-long.1</url>
      <doi>10.18653/v1/2023.acl-long.1</doi>
    </paper>
    <paper id="2">
      <title>A Survey of Neural Methods</title>
      <author><first>Alice</first><last>Johnson</last></author>
      <abstract>A comprehensive survey of neural methods.</abstract>
      <url>2023.acl-long.2</url>
      <doi>10.18653/v1/2023.acl-long.2</doi>
    </paper>
  </volume>
</collection>"""

    def test_parse_volume(self, sample_xml_content):
        """Test parsing XML volume into RawPaper objects."""
        collector = ACLAnthologyCollector()
        venue_info = ACL_VENUES["acl"]

        papers = collector.parse_volume(sample_xml_content, "acl", venue_info)

        assert len(papers) == 2

        # Check first paper
        paper1 = papers[0]
        assert paper1.title == "Test Paper Title"
        assert paper1.source == SourceType.ACL
        assert paper1.year == 2023
        assert paper1.month == 7  # July
        assert paper1.doi == "10.18653/v1/2023.acl-long.1"
        assert paper1.abstract == "This is a test abstract for the paper."
        assert paper1.venue == "Proceedings of ACL 2023 (Volume 1: Long Papers)"
        assert paper1.tier == 0
        assert paper1.is_core is True

        # Check authors
        assert len(paper1.authors) == 2
        assert paper1.authors[0].name == "John Doe"
        assert paper1.authors[1].name == "Jane Smith"

        # Check second paper (survey)
        paper2 = papers[1]
        assert paper2.title == "A Survey of Neural Methods"
        assert paper2.paper_type == PaperType.SURVEY

    def test_parse_author(self):
        """Test author parsing."""
        collector = ACLAnthologyCollector()

        # Create a mock XML element
        import xml.etree.ElementTree as ET
        author_xml = "<author><first>John</first><last>Doe</last></author>"
        author_elem = ET.fromstring(author_xml)

        author = collector._parse_author(author_elem)

        assert isinstance(author, Author)
        assert author.name == "John Doe"

    def test_determine_paper_type(self):
        """Test paper type determination from title."""
        collector = ACLAnthologyCollector()
        import xml.etree.ElementTree as ET

        # Survey paper
        survey_xml = "<paper><title>A Survey of NLP Methods</title></paper>"
        survey_elem = ET.fromstring(survey_xml)
        assert collector._determine_paper_type(survey_elem, "acl") == PaperType.SURVEY

        # Dataset paper
        dataset_xml = "<paper><title>A New Dataset for NER</title></paper>"
        dataset_elem = ET.fromstring(dataset_xml)
        assert collector._determine_paper_type(dataset_elem, "acl") == PaperType.DATASET

        # Demo paper
        demo_xml = "<paper><title>A System Demonstration</title></paper>"
        demo_elem = ET.fromstring(demo_xml)
        assert collector._determine_paper_type(demo_elem, "acl") == PaperType.DEMO

        # Regular paper
        method_xml = "<paper><title>Efficient Transformers</title></paper>"
        method_elem = ET.fromstring(method_xml)
        assert collector._determine_paper_type(method_elem, "acl") == PaperType.METHOD

    def test_parse_volume_empty(self):
        """Test parsing empty or invalid XML."""
        collector = ACLAnthologyCollector()
        venue_info = ACL_VENUES["acl"]

        # Empty content
        papers = collector.parse_volume("", "acl", venue_info)
        assert papers == []

        # Invalid XML
        papers = collector.parse_volume("not valid xml", "acl", venue_info)
        assert papers == []

    def test_parse_volume_no_papers(self):
        """Test parsing XML with no papers."""
        collector = ACLAnthologyCollector()
        venue_info = ACL_VENUES["acl"]

        xml = """<?xml version='1.0' encoding='UTF-8'?>
<collection id="2023.acl">
  <volume id="long">
    <meta>
      <booktitle>Empty Volume</booktitle>
      <year>2023</year>
    </meta>
  </volume>
</collection>"""

        papers = collector.parse_volume(xml, "acl", venue_info)
        assert papers == []

    def test_parse_volume_workshop(self, sample_xml_content):
        """Test venue type detection for workshops."""
        collector = ACLAnthologyCollector()
        venue_info = ACL_VENUES["acl"]

        workshop_xml = """<?xml version='1.0' encoding='UTF-8'?>
<collection id="2023.acl">
  <volume id="workshop">
    <meta>
      <booktitle>Proceedings of the Workshop on NLP</booktitle>
      <year>2023</year>
    </meta>
    <paper id="1">
      <title>Workshop Paper</title>
      <author><first>Test</first><last>Author</last></author>
    </paper>
  </volume>
</collection>"""

        papers = collector.parse_volume(workshop_xml, "acl", venue_info)
        assert len(papers) == 1
        assert papers[0].venue_type == "workshop"

    def test_context_manager_error(self):
        """Test that accessing client without context manager raises error."""
        collector = ACLAnthologyCollector()

        with pytest.raises(RuntimeError, match="async context manager"):
            _ = collector.client


class TestACLPaperParsing:
    """Tests for paper parsing edge cases."""

    def test_parse_paper_with_xml_tags_in_title(self):
        """Test that XML tags are removed from titles."""
        collector = ACLAnthologyCollector()
        venue_info = ACL_VENUES["acl"]

        xml = """<?xml version='1.0' encoding='UTF-8'?>
<collection id="2023.acl">
  <volume id="long">
    <meta>
      <booktitle>ACL 2023</booktitle>
      <year>2023</year>
    </meta>
    <paper id="1">
      <title>Paper with <fixed-case>XML</fixed-case> Tags</title>
      <author><first>Test</first><last>Author</last></author>
    </paper>
  </volume>
</collection>"""

        papers = collector.parse_volume(xml, "acl", venue_info)
        assert len(papers) == 1
        # XML tags should be stripped
        assert "<" not in papers[0].title
        assert ">" not in papers[0].title

    def test_parse_paper_pdf_url(self):
        """Test PDF URL construction."""
        collector = ACLAnthologyCollector()
        venue_info = ACL_VENUES["acl"]

        xml = """<?xml version='1.0' encoding='UTF-8'?>
<collection id="2023.acl">
  <volume id="long">
    <meta>
      <booktitle>ACL 2023</booktitle>
      <year>2023</year>
    </meta>
    <paper id="1">
      <title>Test Paper</title>
      <author><first>Test</first><last>Author</last></author>
      <url>2023.acl-long.1</url>
    </paper>
  </volume>
</collection>"""

        papers = collector.parse_volume(xml, "acl", venue_info)
        assert len(papers) == 1
        assert papers[0].pdf_url == "https://aclanthology.org/2023.acl-long.1.pdf"
        assert papers[0].abstract_url == "https://aclanthology.org/2023.acl-long.1/"
