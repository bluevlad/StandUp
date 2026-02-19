"""
Newsletter report generation and email sending test
Usage: python -m scripts.test_newsletter
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def main():
    from app.core.database import SessionLocal
    from app.core.config import settings
    from app.services.report_service import ReportService
    from app.services.email_service import EmailService
    from app.models.report import ReportStatus
    from datetime import datetime

    print("=== Newsletter Report Test ===")
    print(f"max_projects_per_category: {settings.max_projects_per_category}")
    print(f"max_items_per_project: {settings.max_items_per_project}")

    db = SessionLocal()
    try:
        svc = ReportService()
        report = svc.generate_daily_report(db)
        print(f"\nReport: {report.subject}")
        print(f"Items: {len(report.items)}")

        # Save preview
        preview_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "report_newsletter_preview.html"
        )
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(report.content_html)
        print(f"Preview saved: {preview_path}")

        # Send email
        email_svc = EmailService()
        if email_svc.is_configured:
            result = email_svc.send(
                recipient=settings.gmail_address,
                subject=report.subject + " [Newsletter]",
                html_content=report.content_html,
            )
            if result.success:
                report.status = ReportStatus.SENT
                report.sent_at = datetime.now()
                db.commit()
                print(f"Email sent -> {settings.gmail_address}")
            else:
                print(f"Email failed: {result.error_message}")
        else:
            print("Email not configured, skipping send")

        print("\n=== Test Complete ===")
    finally:
        db.close()


if __name__ == "__main__":
    main()
