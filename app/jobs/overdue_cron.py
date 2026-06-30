def register_jobs(app):
    from app.extensions import scheduler

    @scheduler.scheduled_job("cron", hour=2, minute=0)
    def run_overdue_fines():
        with app.app_context():
            from app.services.fine_service import process_overdue_fines
            process_overdue_fines()

    print("Overdue fines cron registered — runs daily at 2:00 AM")