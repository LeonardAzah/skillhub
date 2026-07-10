from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


class EmailService:
    @staticmethod
    def send_email(
        *,
        subject: str,
        recipient: str,
        template_name: str,
        context: dict,
        from_email: str | None = None,
    ) -> None:
        """
        Send an HTML email with a plain-text fallback.
        """

        from_email = from_email or settings.DEFAULT_FROM_EMAIL

        html_content = render_to_string(template_name, context)

        try:
            text_content = render_to_string(
                template_name.replace(".html", ".txt"),
                context,
            )
        except Exception:
            # If no .txt template exists, fall back to the HTML
            text_content = html_content

        message = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[recipient],
        )

        message.attach_alternative(html_content, "text/html")
        message.send()