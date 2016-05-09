from django.contrib.sites.models import Site


def get_domain_name():
    """
    Gets the domain name of the Site
    """
    try:
        return Site.objects.get(pk=1).domain
    except Site.DoesNotExist:
        error_msg = 'Site is not configured.'
        logger.error(error_msg)
