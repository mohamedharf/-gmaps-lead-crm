from django.core.management.base import BaseCommand
from sales.models import Lead
from sales.logic.email_hunter import AsyncEmailHunter
import asyncio

class Command(BaseCommand):
    help = 'Enrich existing leads with emails asynchronously'

    def add_arguments(self, parser):
        parser.add_argument('--dataset', type=str, help='Filter by dataset ID')
        parser.add_argument('--limit', type=int, help='Limit number of leads to process')

    def handle(self, *args, **options):
        from django.core.cache import cache
        from sales.models import ScraperLog
        from django.utils import timezone

        dataset_id = options.get('dataset')
        limit = options.get('limit')

        # Clear stop flag
        cache.set('stop_enrichment', False, timeout=86400)
        cache.set('enrichment_is_running', True, timeout=86400)

        def log_msg(msg):
            self.stdout.write(msg)
            ScraperLog.objects.create(message=f"[ENRICHMENT] {msg}")

        # 1. Get targets: Include any lead that has a website URL (even if has_website flag is False)
        targets = Lead.objects.exclude(website_url__isnull=True).exclude(website_url='')
        
        if dataset_id:
            targets = targets.filter(dataset_id=dataset_id)
            log_msg(f"Filtering by dataset ID: {dataset_id}")

        # Filter only those with empty emails
        candidates = []
        for r in targets:
            # Check if contact_details exists and if email_list is empty
            has_details = hasattr(r, 'contact_details')
            if not has_details or not r.contact_details.email_list:
                candidates.append(r)
        
        if limit:
            candidates = candidates[:limit]
            log_msg(f"Applied limit: {limit}")

        total_count = len(candidates)
        cache.set('enrichment_total', total_count, timeout=86400)
        cache.set('enrichment_count', 0, timeout=86400)

        log_msg(f"Found {total_count} leads to process. Starting...")
        
        if not candidates:
            cache.set('enrichment_is_running', False, timeout=86400)
            log_msg("No candidates found. Exiting.")
            return

        # Batch processing
        BATCH_SIZE = 10
        hunter = AsyncEmailHunter(concurrency=BATCH_SIZE)
        
        processed_count = 0
        for i in range(0, len(candidates), BATCH_SIZE):
            # Check for stop signal
            if cache.get('stop_enrichment'):
                log_msg("Stop signal received. Halting enrichment.")
                break

            batch = candidates[i:i+BATCH_SIZE]
            urls = [r.website_url for r in batch]
            
            # Run async batch
            try:
                results = asyncio.run(hunter.process_batch(urls))
            except Exception as e:
                log_msg(f"Error in batch: {str(e)}")
                continue
            
            # Save results
            update_count = 0
            from sales.models import ContactDetails
            for r in batch:
                emails = results.get(r.website_url, [])
                if emails:
                    details, _ = ContactDetails.objects.get_or_create(lead=r)
                    current_emails = set(details.email_list or [])
                    current_emails.update(emails)
                    details.email_list = list(current_emails)
                    details.save()
                    update_count += 1
            
            processed_count += len(batch)
            cache.set('enrichment_count', processed_count, timeout=86400)
            log_msg(f"Processed {processed_count}/{total_count}. Found {update_count} new emails in this batch.")

        cache.set('enrichment_is_running', False, timeout=86400)
        log_msg("Enrichment cycle complete.")
